from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_editor_does_not_zero_min_width_for_all_live_overlay_children():
    source = (ROOT / 'web/js/layout-editor.js').read_text(encoding='utf-8')
    assert 'body.gs-layout-edit #stage *{min-width:0}' not in source
    assert 'body.gs-layout-edit .gs-layout-sample *{min-width:0}' in source


def test_scorebug_main_row_keeps_intrinsic_width_and_target_column():
    css = (ROOT / 'web/css/overlay.css').read_text(encoding='utf-8')
    assert '.b-main{display:flex;width:max-content;' in css
    assert '.b-right{display:flex;flex-direction:column;justify-content:center;align-items:flex-end;padding:0 26px;min-width:240px;flex-shrink:0;' in css
    assert '.target-line{font-size:clamp(18px,1.5vw,28px);line-height:1.15;white-space:nowrap;flex-shrink:0}' in css


def test_layout_editor_scales_native_graphics_without_overwriting_intrinsic_dimensions():
    source = (ROOT / 'web/js/layout-editor.js').read_text(encoding='utf-8')
    assert "el.style.setProperty('transform',`scale(${scale})`,'important')" in source
    assert "el.style.width='';el.style.height=''" in source
    assert 'const b=baseSize(el);if(!b)return' in source

def test_overlay_css_does_not_force_native_panels_to_shrink():
    for name in ('overlay.css', 'overlay_fb.css'):
        css = (ROOT / 'web/css' / name).read_text(encoding='utf-8')
        assert 'max-width:calc(100% - 32px)' not in css
        assert 'max-height:calc(100% - 32px)' not in css
