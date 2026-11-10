from law_rag.segmentation import PREAMBLE_ID, PREAMBLE_TITLE, segment_clauses


def test_segment_article_headings_variants_and_preamble() -> None:
    text = (
        "KONUT KİRA SÖZLEŞMESİ\n"
        "Kiraya veren: Ali Veli\n"
        "MADDE 1 - KONU\n"
        "Kiralanan daire konut olarak kullanılır.\n"
        "Madde 2: Kira Bedeli\n"
        "Madde 5 uyarınca ödeme yapılır.\n"
        "1. madde genel kuraldır.\n"
        "ARTICLE 3.\n"
        "Süre bir yıldır.\n"
    )

    clauses = segment_clauses(text)

    assert [clause.id for clause in clauses] == [PREAMBLE_ID, "clause-1", "clause-2", "clause-3"]
    assert clauses[0].title == PREAMBLE_TITLE
    assert "KONUT KİRA SÖZLEŞMESİ" in clauses[0].text
    assert clauses[1].title == "MADDE 1 - KONU"
    assert "Madde 5 uyarınca" in clauses[2].text
    assert len(clauses) == 4


def test_segment_top_numbered_headings_ignores_dates_currency_and_restarting_lists() -> None:
    text = (
        "1. TARAFLAR\n"
        "01.02.2024 tarihinde imzalanmıştır.\n"
        "2. BEDEL\n"
        "1. kalem ön ödemedir.\n"
        "450.000 TL peşin ödenir.\n"
        "2.1 Alt madde açıklaması.\n"
        "3. FESİH\n"
        "Taraflar yazılı bildirimle feshedebilir.\n"
    )

    clauses = segment_clauses(text)

    assert [clause.id for clause in clauses] == ["clause-1", "clause-2", "clause-3"]
    assert clauses[1].title == "2. BEDEL"
    assert "1. kalem ön ödemedir." in clauses[1].text
    assert "450.000 TL peşin ödenir." in clauses[1].text
    assert "2.1 Alt madde açıklaması." in clauses[1].text


def test_segment_parenthesis_numbered_headings() -> None:
    text = (
        "1) Konu\n"
        "Hizmet verilir.\n"
        "2) Süre\n"
        "Süre 12 aydır.\n"
    )

    clauses = segment_clauses(text)

    assert [clause.id for clause in clauses] == ["clause-1", "clause-2"]
    assert clauses[0].title == "1) Konu"
    assert clauses[1].title == "2) Süre"


def test_segment_sub_numbered_headings_when_no_top_headings() -> None:
    text = (
        "Başlık Metni\n"
        "1.1 Taraflar arasında hizmet ilişkisi kurulur.\n"
        "1.2 Bedel aylık faturalanır.\n"
        "2.1 Gizlilik süresi iki yıldır.\n"
    )

    clauses = segment_clauses(text)

    assert [clause.id for clause in clauses] == [PREAMBLE_ID, "clause-1", "clause-2", "clause-3"]
    assert clauses[1].title == "1.1 Taraflar arasında hizmet ilişkisi kurulur."
    assert clauses[3].title == "2.1 Gizlilik süresi iki yıldır."


def test_segment_falls_back_to_paragraphs_without_headings() -> None:
    text = (
        "Birinci paragraf açıklaması burada yer alır.\n\n"
        "İkinci paragraf sorumluluk sınırını düzenler.\n"
    )

    clauses = segment_clauses(text)

    assert [clause.id for clause in clauses] == ["clause-1", "clause-2"]
    assert clauses[0].title is None
    assert "Birinci paragraf" in clauses[0].text
    assert "İkinci paragraf" in clauses[1].text

