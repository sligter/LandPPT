from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.slide.edit_agent.draft import SlideDraft
from landppt.services.slide.edit_agent.html_safety import compute_slide_html_hash, validate_slide_html
from landppt.services.slide.slide_edit_agent_service import (
    SlideEditAgentApplyRequest, SlideEditAgentContext, SlideEditAgentRequest, SlideEditToolbox,
)
from landppt.services.slide.svg_page.edit import parse_svg_soup
from landppt.services.slide.svg_page.shell import build_slide_html


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<defs><linearGradient id="paint"><stop offset="0" stop-color="#ff0000"/></linearGradient>
<symbol id="custom" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/></symbol></defs>
<rect id="card" x="80" y="80" width="800" height="400" fill="url(#paint)"/>
<text id="title" x="100" y="160" font-size="36"><tspan x="100">原始标题</tspan></text>
<use id="icon" href="#custom" x="900" y="150" width="64" height="64"/>
</svg>'''
BASE = build_slide_html(SVG)


def toolbox():
    request = SlideEditAgentRequest(projectId='p', slideIndex=1, userRequest='修改标题', slideContent=BASE)
    draft = SlideDraft(BASE)
    return SlideEditToolbox(SlideEditAgentContext.from_request(request), draft), draft


def test_svg_agent_edits_coordinates_and_text_without_lowercasing_xml_and_can_undo():
    tools, draft = toolbox()
    assert tools.execute('set_attributes', {'selector': '#card', 'attributes': {'x': '120', 'transform': 'translate(10 20)'}}).ok
    assert tools.execute('set_text', {'selector': '#title tspan', 'text': '已编辑标题'}).ok
    assert tools.execute('validate_draft', {}).ok
    saved = validate_slide_html(draft.html, baseline_html=BASE)
    assert saved.valid, saved.errors
    root = parse_svg_soup(saved.sanitized_html)
    assert root.svg['viewBox'] == '0 0 1280 720'
    assert root.find('linearGradient')['id'] == 'paint'
    assert root.find(id='card')['x'] == '120'
    assert root.find(id='icon')['href'] == '#custom'
    assert '已编辑标题' in root.get_text()
    assert draft.undo()
    assert '原始标题' in draft.html


def test_svg_fragment_resolves_existing_symbols_and_does_not_duplicate_ids():
    _, draft = toolbox()
    fragment = draft.parse_fragment('<use href="#custom" x="1" y="2"/>')
    assert len(fragment) == 1 and fragment[0]['href'] == '#custom'
    assert fragment[0]['id'] not in {node.get('id') for node in draft.soup.find_all(True)}
    with pytest.raises(ValueError):
        draft.parse_fragment('<foreignObject><div>unsafe</div></foreignObject>')


@pytest.mark.parametrize('attack', [
    '<script>alert(1)</script>', '<rect onclick="alert(1)"/>',
    '<use href="https://example.test/x.svg#icon"/>',
    '<image href="https://example.test/tracker.png"/>',
    '<foreignObject><div>HTML</div></foreignObject>',
])
def test_svg_edits_reject_new_executable_or_external_content(attack):
    result = validate_slide_html(SVG.replace('</svg>', attack + '</svg>'), baseline_html=BASE)
    assert not result.valid


def test_svg_validation_uses_trusted_shell_and_discards_new_shell_without_baseline():
    attack = BASE.replace('</body>', '<script>alert(1)</script></body>')
    assert '<script' not in validate_slide_html(attack).sanitized_html
    assert '<script' not in validate_slide_html(attack, baseline_html=BASE).sanitized_html
    assert not validate_slide_html('<div>replacement</div>', baseline_html=BASE).valid


def test_editing_can_add_library_symbol_without_a_broken_reference():
    result = validate_slide_html(SVG.replace('</svg>', '<use href="#ic-check" width="40" height="40"/></svg>'), baseline_html=BASE)
    assert result.valid, result.errors
    assert parse_svg_soup(result.sanitized_html).find('symbol', id='ic-check') is not None


@pytest.mark.asyncio
async def test_svg_apply_preserves_mode_and_saves_valid_xml(monkeypatch):
    from landppt.web.route_modules import slide_edit_agent_routes as routes
    project = SimpleNamespace(slides_data=[{'render_mode': 'svg', 'html_content': BASE, 'generation_failed': True, 'svg_report': {'old': True}}])
    service = SimpleNamespace(project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project)))
    db = SimpleNamespace(save_single_slide=AsyncMock(return_value=True))
    monkeypatch.setattr(routes, 'get_ppt_service_for_user', lambda uid: service)
    monkeypatch.setattr(routes, 'DatabaseProjectManager', lambda: db)
    request = SlideEditAgentApplyRequest(proposalId='edit', projectId='p', slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(BASE), htmlContent=SVG.replace('原始标题', '保存标题'), slideData={'render_mode': 'html'})
    result = await routes.apply_slide_edit_agent_proposal(request, SimpleNamespace(id=7))
    assert result['success']
    saved = db.save_single_slide.await_args.args[2]
    assert saved['render_mode'] == 'svg' and saved['is_user_edited']
    assert 'generation_failed' not in saved and 'svg_report' not in saved
    assert '保存标题' in saved['html_content'] and 'viewBox' in saved['html_content']
    service.project_manager.get_project.assert_awaited_once_with('p', user_id=7)
