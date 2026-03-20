"""Unit tests for app/parser/extract.py.

All tests use small inline XHTML snippets — no full book files are needed.
Each extraction function is tested for its happy path and for graceful
handling of missing or malformed elements.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.parser.extract import (
    _era_for_book_number,
    copy_illustrations,
    extract_choices,
    extract_combat_encounters,
    extract_crt,
    extract_disciplines,
    extract_scenes,
    extract_starting_equipment,
)
from app.parser.types import BookData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _soup(html: str) -> BeautifulSoup:
    """Parse an HTML string with html.parser."""
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# Era determination
# ---------------------------------------------------------------------------

class TestEraForBookNumber:
    def test_book_1_is_kai(self) -> None:
        assert _era_for_book_number(1) == "kai"

    def test_book_5_is_kai(self) -> None:
        assert _era_for_book_number(5) == "kai"

    def test_book_6_is_magnakai(self) -> None:
        assert _era_for_book_number(6) == "magnakai"

    def test_book_12_is_magnakai(self) -> None:
        assert _era_for_book_number(12) == "magnakai"

    def test_book_13_is_grand_master(self) -> None:
        assert _era_for_book_number(13) == "grand_master"

    def test_book_20_is_grand_master(self) -> None:
        assert _era_for_book_number(20) == "grand_master"

    def test_book_21_is_new_order(self) -> None:
        assert _era_for_book_number(21) == "new_order"

    def test_book_29_is_new_order(self) -> None:
        assert _era_for_book_number(29) == "new_order"


# ---------------------------------------------------------------------------
# Book metadata
# ---------------------------------------------------------------------------

class TestExtractBookMetadata:
    def test_extracts_slug_from_filename(self, tmp_path: Path) -> None:
        xhtml = tmp_path / "01fftd.htm"
        xhtml.write_text("<html><head><title>Flight from the Dark</title></head><body></body></html>")
        from app.parser.extract import extract_book_metadata
        result = extract_book_metadata(xhtml)
        assert result.slug == "01fftd"

    def test_extracts_book_number_from_slug(self, tmp_path: Path) -> None:
        xhtml = tmp_path / "06tkot.htm"
        xhtml.write_text("<html><head><title>The Kingdoms of Terror</title></head><body></body></html>")
        from app.parser.extract import extract_book_metadata
        result = extract_book_metadata(xhtml)
        assert result.number == 6

    def test_extracts_title_from_title_element(self, tmp_path: Path) -> None:
        xhtml = tmp_path / "01fftd.htm"
        xhtml.write_text("<html><head><title>Flight from the Dark</title></head><body></body></html>")
        from app.parser.extract import extract_book_metadata
        result = extract_book_metadata(xhtml)
        assert result.title == "Flight from the Dark"

    def test_falls_back_to_h1_when_no_title(self, tmp_path: Path) -> None:
        xhtml = tmp_path / "01fftd.htm"
        xhtml.write_text("<html><head></head><body><h1>Flight from the Dark</h1></body></html>")
        from app.parser.extract import extract_book_metadata
        result = extract_book_metadata(xhtml)
        assert result.title == "Flight from the Dark"

    def test_era_set_correctly_for_book_1(self, tmp_path: Path) -> None:
        xhtml = tmp_path / "01fftd.htm"
        xhtml.write_text("<html><head><title>Book 1</title></head><body></body></html>")
        from app.parser.extract import extract_book_metadata
        result = extract_book_metadata(xhtml)
        assert result.era == "kai"

    def test_returns_book_data_instance(self, tmp_path: Path) -> None:
        xhtml = tmp_path / "01fftd.htm"
        xhtml.write_text("<html><head><title>Test</title></head><body></body></html>")
        from app.parser.extract import extract_book_metadata
        result = extract_book_metadata(xhtml)
        assert isinstance(result, BookData)


# ---------------------------------------------------------------------------
# Scene extraction
# ---------------------------------------------------------------------------

class TestExtractScenes:
    _SINGLE_SCENE = """
    <html><body>
    <div class="numbered">
      <h3><a name="sect1">1</a></h3>
      <p>You stand at the edge of a dark forest.</p>
      <p>The wind howls through the trees.</p>
      <p class="choice"><a href="#sect85">Turn to 85</a>.</p>
    </div>
    </body></html>
    """

    def test_extracts_single_scene(self) -> None:
        soup = _soup(self._SINGLE_SCENE)
        scenes = extract_scenes(soup)
        assert len(scenes) == 1
        assert scenes[0].number == 1

    def test_extracts_scene_html_id(self) -> None:
        soup = _soup(self._SINGLE_SCENE)
        scenes = extract_scenes(soup)
        assert scenes[0].html_id == "sect1"

    def test_extracts_narrative_text(self) -> None:
        soup = _soup(self._SINGLE_SCENE)
        scenes = extract_scenes(soup)
        assert "dark forest" in scenes[0].narrative
        assert "wind howls" in scenes[0].narrative

    def test_narrative_excludes_choice_paragraphs(self) -> None:
        soup = _soup(self._SINGLE_SCENE)
        scenes = extract_scenes(soup)
        # The choice "Turn to 85" should not appear in narrative
        assert "Turn to 85" not in scenes[0].narrative

    def test_extracts_multiple_scenes(self) -> None:
        html = """
        <html><body>
        <div class="numbered">
          <h3><a name="sect1">1</a></h3>
          <p>Scene one text.</p>
        </div>
        <div class="numbered">
          <h3><a name="sect2">2</a></h3>
          <p>Scene two text.</p>
        </div>
        </body></html>
        """
        scenes = extract_scenes(_soup(html))
        assert len(scenes) == 2
        assert scenes[0].number == 1
        assert scenes[1].number == 2

    def test_handles_section_tag_instead_of_div(self) -> None:
        html = """
        <html><body>
        <section class="numbered">
          <h3><a name="sect10">10</a></h3>
          <p>A section element scene.</p>
        </section>
        </body></html>
        """
        scenes = extract_scenes(_soup(html))
        assert len(scenes) == 1
        assert scenes[0].number == 10

    def test_returns_empty_list_when_no_numbered_blocks(self) -> None:
        html = "<html><body><p>No numbered sections here.</p></body></html>"
        scenes = extract_scenes(_soup(html))
        assert scenes == []

    def test_handles_id_attribute_instead_of_name(self) -> None:
        html = """
        <html><body>
        <div class="numbered">
          <h3><span id="sect42">42</span></h3>
          <p>Scene with id attribute.</p>
        </div>
        </body></html>
        """
        scenes = extract_scenes(_soup(html))
        assert len(scenes) == 1
        assert scenes[0].number == 42

    def test_scene_has_choices_attached(self) -> None:
        soup = _soup(self._SINGLE_SCENE)
        scenes = extract_scenes(soup)
        assert len(scenes[0].choices) == 1
        assert scenes[0].choices[0].target_scene_number == 85

    def test_scene_narrative_excludes_combat_paragraphs(self) -> None:
        html = """
        <html><body>
        <div class="numbered">
          <h3><a name="sect5">5</a></h3>
          <p>A Kraan blocks your path.</p>
          <p class="combat">Kraan: <small>COMBAT SKILL</small> 16   <small>ENDURANCE</small> 24</p>
        </div>
        </body></html>
        """
        scenes = extract_scenes(_soup(html))
        assert len(scenes) == 1
        assert "COMBAT SKILL" not in scenes[0].narrative

    def test_scene_with_illustration(self) -> None:
        html = """
        <html><body>
        <div class="numbered">
          <h3><a name="sect3">3</a></h3>
          <img src="illus/img001.png" alt=""/>
          <p>Scene with illustration.</p>
        </div>
        </body></html>
        """
        scenes = extract_scenes(_soup(html))
        assert scenes[0].illustration_path is not None
        assert "img001.png" in scenes[0].illustration_path


# ---------------------------------------------------------------------------
# Choice extraction
# ---------------------------------------------------------------------------

class TestExtractChoices:
    def test_extracts_single_choice(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice"><a href="#sect141">Turn to 141</a>.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert len(choices) == 1
        assert choices[0].target_scene_number == 141

    def test_extracts_choice_raw_text(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice">If you wish to investigate, <a href="#sect99">turn to 99</a>.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert "investigate" in choices[0].raw_text

    def test_extracts_multiple_choices_in_order(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice"><a href="#sect85">Turn to 85</a>.</p>
          <p class="choice"><a href="#sect141">Turn to 141</a>.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert len(choices) == 2
        assert choices[0].target_scene_number == 85
        assert choices[1].target_scene_number == 141

    def test_choice_ordinals_start_at_one(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice"><a href="#sect10">Turn to 10</a>.</p>
          <p class="choice"><a href="#sect20">Turn to 20</a>.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert choices[0].ordinal == 1
        assert choices[1].ordinal == 2

    def test_falls_back_to_text_pattern_when_no_href(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice">If you succeed, turn to 200.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert len(choices) == 1
        assert choices[0].target_scene_number == 200

    def test_skips_choice_with_no_target(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice">This choice has no scene reference.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert choices == []

    def test_returns_empty_list_when_no_choices(self) -> None:
        html = """
        <div class="numbered">
          <p>No choices here.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert choices == []

    def test_complex_choice_text_with_condition(self) -> None:
        html = """
        <div class="numbered">
          <p class="choice">If you have 10 Gold Crowns and wish to pay him,
          <a href="#sect262">turn to 262</a>.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        choices = extract_choices(tag)
        assert len(choices) == 1
        assert choices[0].target_scene_number == 262


# ---------------------------------------------------------------------------
# Combat encounter extraction
# ---------------------------------------------------------------------------

class TestExtractCombatEncounters:
    def test_extracts_single_combat(self) -> None:
        html = """
        <div class="numbered">
          <p class="combat">Kraan: <small>COMBAT SKILL</small> 16   <small>ENDURANCE</small> 24</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert len(encounters) == 1
        assert encounters[0].enemy_name == "Kraan"
        assert encounters[0].enemy_cs == 16
        assert encounters[0].enemy_end == 24

    def test_extracts_multiple_combats(self) -> None:
        html = """
        <div class="numbered">
          <p class="combat">Helghast: <small>COMBAT SKILL</small> 22   <small>ENDURANCE</small> 30</p>
          <p class="combat">Kraan: <small>COMBAT SKILL</small> 16   <small>ENDURANCE</small> 24</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert len(encounters) == 2
        assert encounters[0].enemy_name == "Helghast"
        assert encounters[0].enemy_cs == 22
        assert encounters[1].enemy_name == "Kraan"

    def test_combat_ordinals_start_at_one(self) -> None:
        html = """
        <div class="numbered">
          <p class="combat">Foe A: <small>COMBAT SKILL</small> 10   <small>ENDURANCE</small> 10</p>
          <p class="combat">Foe B: <small>COMBAT SKILL</small> 12   <small>ENDURANCE</small> 15</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert encounters[0].ordinal == 1
        assert encounters[1].ordinal == 2

    def test_skips_malformed_combat_element(self) -> None:
        html = """
        <div class="numbered">
          <p class="combat">This is not a valid combat block.</p>
          <p class="combat">Kraan: <small>COMBAT SKILL</small> 16   <small>ENDURANCE</small> 24</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert len(encounters) == 1
        assert encounters[0].enemy_name == "Kraan"

    def test_returns_empty_list_when_no_combat(self) -> None:
        html = """
        <div class="numbered">
          <p>Peaceful scene with no combat.</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert encounters == []

    def test_enemy_name_with_spaces(self) -> None:
        html = """
        <div class="numbered">
          <p class="combat">Black Bear: <small>COMBAT SKILL</small> 14   <small>ENDURANCE</small> 20</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert encounters[0].enemy_name == "Black Bear"

    def test_plain_text_combat_without_small_tags(self) -> None:
        """Some books render combat stats as plain text without <small> tags."""
        html = """
        <div class="numbered">
          <p class="combat">Drakkar: COMBAT SKILL 18   ENDURANCE 28</p>
        </div>
        """
        tag = _soup(html).find("div", class_="numbered")
        encounters = extract_combat_encounters(tag)
        assert len(encounters) == 1
        assert encounters[0].enemy_cs == 18
        assert encounters[0].enemy_end == 28


# ---------------------------------------------------------------------------
# Combat Results Table extraction
# ---------------------------------------------------------------------------

class TestExtractCrt:
    _CRT_HTML = """
    <html><body>
    <a name="crtable"></a>
    <table>
      <tr>
        <th>Random Number</th>
        <th>-6 to -5</th>
        <th>-4 to -3</th>
        <th>0 to +1</th>
      </tr>
      <tr>
        <td>0</td>
        <td>0/6</td>
        <td>0/5</td>
        <td>1/4</td>
      </tr>
      <tr>
        <td>5</td>
        <td>k/0</td>
        <td>6/0</td>
        <td>k/0</td>
      </tr>
    </table>
    </body></html>
    """

    def test_extracts_crt_rows(self) -> None:
        rows = extract_crt(_soup(self._CRT_HTML))
        # 2 data rows × 3 columns = 6 rows
        assert len(rows) == 6

    def test_extracts_random_number(self) -> None:
        rows = extract_crt(_soup(self._CRT_HTML))
        rn_values = {r.random_number for r in rows}
        assert 0 in rn_values
        assert 5 in rn_values

    def test_parses_kill_as_none_for_enemy(self) -> None:
        rows = extract_crt(_soup(self._CRT_HTML))
        # Find a k/0 row (rn=5, first column)
        kill_rows = [r for r in rows if r.random_number == 5 and r.enemy_loss is None]
        assert kill_rows, "Expected at least one k/0 row"
        assert kill_rows[0].hero_loss == 0

    def test_parses_numeric_losses(self) -> None:
        rows = extract_crt(_soup(self._CRT_HTML))
        zero_rn = [r for r in rows if r.random_number == 0 and r.combat_ratio_min == -6]
        assert zero_rn
        assert zero_rn[0].enemy_loss == 0
        assert zero_rn[0].hero_loss == 6

    def test_returns_empty_list_when_no_crt_anchor(self) -> None:
        html = "<html><body><p>No CRT here.</p></body></html>"
        rows = extract_crt(_soup(html))
        assert rows == []

    def test_parses_ratio_brackets_correctly(self) -> None:
        rows = extract_crt(_soup(self._CRT_HTML))
        brackets = {(r.combat_ratio_min, r.combat_ratio_max) for r in rows}
        assert (-6, -5) in brackets
        assert (0, 1) in brackets


# ---------------------------------------------------------------------------
# Discipline extraction
# ---------------------------------------------------------------------------

class TestExtractDisciplines:
    _DISC_HTML = """
    <html><body>
    <div>
      <a name="discplnz"></a>
      <h4><a name="camflge">Camouflage</a></h4>
      <p>This Discipline enables Lone Wolf to blend in with his surroundings.</p>
      <p>It is particularly effective in woodlands.</p>
      <h4><a name="animknow">Animal Kinship</a></h4>
      <p>This Discipline allows Lone Wolf to communicate with animals.</p>
    </div>
    </body></html>
    """

    def test_extracts_discipline_names(self) -> None:
        disciplines = extract_disciplines(_soup(self._DISC_HTML))
        names = [d.name for d in disciplines]
        assert "Camouflage" in names
        assert "Animal Kinship" in names

    def test_extracts_discipline_html_id(self) -> None:
        disciplines = extract_disciplines(_soup(self._DISC_HTML))
        camouflage = next(d for d in disciplines if "Camouflage" in d.name)
        assert camouflage.html_id == "camflge"

    def test_extracts_discipline_description(self) -> None:
        disciplines = extract_disciplines(_soup(self._DISC_HTML))
        camouflage = next(d for d in disciplines if "Camouflage" in d.name)
        assert "blend in" in camouflage.description

    def test_description_spans_multiple_paragraphs(self) -> None:
        disciplines = extract_disciplines(_soup(self._DISC_HTML))
        camouflage = next(d for d in disciplines if "Camouflage" in d.name)
        assert "woodlands" in camouflage.description

    def test_returns_empty_list_when_no_anchor(self) -> None:
        html = "<html><body><p>No disciplines here.</p></body></html>"
        disciplines = extract_disciplines(_soup(html))
        assert disciplines == []

    def test_handles_discipline_without_inner_anchor(self) -> None:
        html = """
        <html><body>
        <div>
          <a name="discplnz"></a>
          <h4>Sixth Sense</h4>
          <p>A discipline for detecting danger.</p>
        </div>
        </body></html>
        """
        disciplines = extract_disciplines(_soup(html))
        assert len(disciplines) == 1
        assert disciplines[0].name == "Sixth Sense"
        assert disciplines[0].html_id == ""


# ---------------------------------------------------------------------------
# Starting equipment extraction
# ---------------------------------------------------------------------------

class TestExtractStartingEquipment:
    _EQUIP_HTML = """
    <html><body>
    <div>
      <a name="equipmnt"></a>
      <ul>
        <li>Sword</li>
        <li>Backpack</li>
        <li>2 Meals</li>
        <li>25 Gold Crowns</li>
      </ul>
    </div>
    </body></html>
    """

    def test_extracts_equipment_items(self) -> None:
        items = extract_starting_equipment(_soup(self._EQUIP_HTML))
        names = [i.item_name for i in items]
        assert "Sword" in names
        assert "Backpack" in names

    def test_classifies_sword_as_weapon(self) -> None:
        items = extract_starting_equipment(_soup(self._EQUIP_HTML))
        sword = next(i for i in items if i.item_name == "Sword")
        assert sword.item_type == "weapon"

    def test_classifies_gold_crowns_correctly(self) -> None:
        items = extract_starting_equipment(_soup(self._EQUIP_HTML))
        gold = next(i for i in items if "Gold Crowns" in i.item_name)
        assert gold.item_type == "gold"

    def test_classifies_meal_as_meal(self) -> None:
        items = extract_starting_equipment(_soup(self._EQUIP_HTML))
        meal = next(i for i in items if "Meal" in i.item_name)
        assert meal.item_type == "meal"

    def test_returns_empty_list_when_no_anchor(self) -> None:
        html = "<html><body><p>No equipment here.</p></body></html>"
        items = extract_starting_equipment(_soup(html))
        assert items == []

    def test_returns_empty_list_when_no_list_items(self) -> None:
        html = """
        <html><body>
        <a name="equipmnt"></a>
        <p>Equipment text but no list.</p>
        </body></html>
        """
        items = extract_starting_equipment(_soup(html))
        assert items == []

    def test_quantity_defaults_to_one(self) -> None:
        items = extract_starting_equipment(_soup(self._EQUIP_HTML))
        assert all(i.quantity == 1 for i in items)


# ---------------------------------------------------------------------------
# copy_illustrations
# ---------------------------------------------------------------------------

class TestCopyIllustrations:
    def test_copies_png_files(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "img001.png").write_bytes(b"\x89PNG")
        (src_dir / "img002.png").write_bytes(b"\x89PNG")
        dest_dir = tmp_path / "dest"

        copied = copy_illustrations(src_dir, "01fftd", dest_dir)

        assert len(copied) == 2
        assert (dest_dir / "01fftd" / "img001.png").exists()
        assert (dest_dir / "01fftd" / "img002.png").exists()

    def test_creates_destination_directory(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "img001.jpg").write_bytes(b"fake jpg")
        dest_dir = tmp_path / "nonexistent" / "dest"

        copy_illustrations(src_dir, "01fftd", dest_dir)

        assert (dest_dir / "01fftd").is_dir()

    def test_returns_empty_list_when_no_images(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "book.htm").write_text("not an image")
        dest_dir = tmp_path / "dest"

        copied = copy_illustrations(src_dir, "01fftd", dest_dir)

        assert copied == []

    def test_copies_multiple_formats(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.png").write_bytes(b"png")
        (src_dir / "b.jpg").write_bytes(b"jpg")
        (src_dir / "c.gif").write_bytes(b"gif")
        dest_dir = tmp_path / "dest"

        copied = copy_illustrations(src_dir, "01fftd", dest_dir)

        assert len(copied) == 3
