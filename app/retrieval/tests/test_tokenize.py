from retrieval.tokenize import tokenize


def test_particles_split_so_subject_forms_share_stem():
    a = tokenize("세종이 훈민정음을 만들었다.")
    b = tokenize("세종은 백성을 사랑하였다.")
    assert "세종" in a
    assert "세종" in b


def test_punctuation_and_whitespace_removed():
    toks = tokenize("경복궁, 경회루!  (근정전) ...")
    for t in toks:
        assert t.strip() == t and t != ""
        assert t not in {",", "!", "(", ")", ".", "..."}
    assert "경복궁" in toks


def test_numbers_kept_and_lowercased():
    toks = tokenize("Seoul 관광은 1443년과 2019년 자료를 비교한다.")
    assert "1443" in toks
    assert "2019" in toks
    assert "seoul" in toks
    assert "Seoul" not in toks


def test_empty_text():
    assert tokenize("") == []
    assert tokenize("   \n\t ") == []


def test_subject_and_topic_particles_give_same_tokens():
    assert tokenize("세종이") == tokenize("세종은") == ["세종"]


def test_particles_endings_suffixes_and_copula_dropped():
    # 은(JX), 되(XSV), 었(EP), 나(EC) are dropped; content morphemes stay
    assert tokenize("훈민정음은 언제 반포되었나") == ["훈민정음", "언제", "반포"]
    # 이(VCP) + 며(EC)/다(EF) and 은/부터/까지(JX) dropped; times stay
    toks = tokenize("관람 시간은 09:00부터 18:00까지이며 입장 마감은 17:00이다.")
    for t in ["은", "부터", "까지", "이", "며", "다"]:
        assert t not in toks
    assert {"관람", "시간", "입장", "마감", "09:00", "18:00", "17:00"} <= set(toks)
    # 하(XSV) + ㄴ다(EF) dropped
    assert tokenize("프린터를 교체한다") == ["프린터", "교체"]


def test_negative_copula_dropped():
    assert tokenize("경복궁이 아니다") == ["경복궁"]
