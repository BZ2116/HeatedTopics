from pathlib import Path

from openpyxl import Workbook

from src.search_discovery.persona_profiles import (
    build_creator_profile,
    load_persona_profiles_from_excel,
    persona_to_retrieval_document,
)


def _write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "工作表1"
    sheet.append(["一级赛道", "二级赛道", "人设"])
    sheet.append(
        [
            "科技AI",
            "AI工具应用",
            "经管学生视角的AI工具体验官，专门测试写作、学习和汇报场景。",
        ]
    )
    sheet.append(
        [
            "财经商业",
            "普通人理财",
            "不讲暴富故事，只用生活化案例拆解基金、存款、消费和风险。",
        ]
    )
    workbook.save(path)


def test_load_persona_profiles_from_excel_normalizes_rows(tmp_path):
    source = tmp_path / "personas.xlsx"
    _write_workbook(source)

    personas = load_persona_profiles_from_excel(source)

    assert [persona.profile_id for persona in personas] == ["persona_0001", "persona_0002"]
    assert personas[0].primary_track == "科技AI"
    assert personas[0].secondary_track == "AI工具应用"
    assert personas[0].profile_type == "tech_ai_creator"
    assert personas[0].track_tags == ["科技AI", "AI工具应用"]
    assert personas[0].source == {"file": "personas.xlsx", "sheet": "工作表1", "row": 2}
    assert "AI工具应用" in personas[0].retrieval_text
    assert "写作" in personas[0].custom_keywords


def test_persona_to_retrieval_document_keeps_search_fields():
    persona = load_persona_profiles_from_excel_row(
        ["财经商业", "普通人理财", "用生活化案例拆解基金、存款、消费和风险。"]
    )

    document = persona_to_retrieval_document(persona)

    assert document["schema_version"] == "0.1"
    assert document["profile_id"] == "persona_0001"
    assert document["primary_track"] == "财经商业"
    assert document["secondary_track"] == "普通人理财"
    assert document["profile_type"] == "business_startup_creator"
    assert document["sensitivity_level"] == "internal"
    assert document["track_tags"] == ["财经商业", "普通人理财"]
    assert "基金" in document["custom_keywords"]
    assert "生活化案例" in document["retrieval_text"]


def test_build_creator_profile_exports_v2_compatible_shape(tmp_path):
    source = tmp_path / "personas.xlsx"
    _write_workbook(source)
    persona = load_persona_profiles_from_excel(source)[0]

    profile = build_creator_profile(persona)

    assert profile["creator_id"] == "persona_0001"
    assert profile["role"] == persona.persona_text
    assert profile["profile_type"] == "tech_ai_creator"
    assert profile["track_tags"] == ["科技AI", "AI工具应用"]
    assert "AI" in profile["custom_keywords"]
    assert profile["content_goal"] == "基于该用户画像发现适合内容创作的国内热点"


def load_persona_profiles_from_excel_row(row):
    source = Path("personas.xlsx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "工作表1"
    sheet.append(["一级赛道", "二级赛道", "人设"])
    sheet.append(row)
    tmp = Path("/tmp/persona_profile_test.xlsx")
    workbook.save(tmp)
    try:
        return load_persona_profiles_from_excel(tmp)[0]
    finally:
        tmp.unlink(missing_ok=True)
