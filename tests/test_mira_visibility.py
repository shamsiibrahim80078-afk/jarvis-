"""Visibility / contain-fit for Mira uploads."""

from jarvis.mira.visibility import (
    analyze_upload_visibility,
    cover_visible_ratio,
    parse_visibility_reply,
    probe_size,
)


def test_cover_ratio_landscape_into_shorts():
    # 1920x1080 into 1080x1920 → heavy side crop
    r = cover_visible_ratio(1920, 1080, 1080, 1920)
    assert r < 0.6


def test_cover_ratio_same_aspect():
    assert cover_visible_ratio(1080, 1920, 1080, 1920) == 1.0


def test_analyze_needs_ask_for_wide_shots(tmp_path):
    from PIL import Image

    img = tmp_path / "wide.png"
    Image.new("RGB", (1600, 900), color=(20, 30, 40)).save(img)
    out = analyze_upload_visibility([img], aspect="9:16")
    assert out["needs_ask"] is True
    assert out["worst_visible"] < 0.88


def test_analyze_ok_when_matching(tmp_path):
    from PIL import Image

    img = tmp_path / "tall.png"
    Image.new("RGB", (1080, 1920), color=(20, 30, 40)).save(img)
    out = analyze_upload_visibility([img], aspect="9:16")
    assert out["needs_ask"] is False


def test_parse_show_full():
    r = parse_visibility_reply("show full")
    assert r is not None
    assert r["fit_mode"] == "contain"


def test_parse_crop_fill():
    r = parse_visibility_reply("crop fill")
    assert r is not None
    assert r["fit_mode"] == "cover"


def test_parse_landscape():
    r = parse_visibility_reply("16:9")
    assert r is not None
    assert r["aspect"] == "16:9"
    assert r["fit_mode"] == "contain"


def test_vf_contain():
    from jarvis.mira.fast_encode import _vf_fit

    vf = _vf_fit(1080, 1920, 30, "contain")
    assert "decrease" in vf
    assert "pad=" in vf
    assert "crop=" not in vf


def test_vf_cover():
    from jarvis.mira.fast_encode import _vf_fit

    vf = _vf_fit(1080, 1920, 30, "cover")
    assert "increase" in vf
    assert "crop=" in vf


def test_probe_png(tmp_path):
    from PIL import Image

    img = tmp_path / "a.png"
    Image.new("RGB", (640, 480), color=0).save(img)
    assert probe_size(img) == (640, 480)
