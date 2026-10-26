import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import httpx2

from email_agent.config import Config
from email_agent.main import load_fixtures, main, split_bulk
from email_agent.parser import html_to_text, is_bulk, parse_mime, strip_quoted, truncate
from email_agent.render import render_digest
from email_agent.sources import RawEmail, dedupe
from email_agent.sources.graph_source import to_raw_email
from email_agent.summarizer import (Digest, DigestItem, Summarizer, _format_emails, estimate_tokens,
                                    overhead_tokens,
                                    fallback_digest)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 26, 7, tzinfo=timezone.utc)


def _emails():
    return dedupe(load_fixtures(FIXTURES, 1500))


def test_plain_text_drops_quoted_reply():
    fields = parse_mime((FIXTURES / "gmail/01_internship.eml").read_bytes())
    assert fields["subject"] == "Quant Research Internship - next round"
    assert "Fri 30 Oct 23:59" in fields["body"]
    assert "attached is my CV" not in fields["body"]
    assert "wrote:" not in fields["body"]
    assert fields["received"].tzinfo is not None
    assert fields["bulk"] is False


def test_html_part_is_converted_and_scripts_removed():
    fields = parse_mime((FIXTURES / "gmail/02_promo.eml").read_bytes())
    assert "Up to 90% off" in fields["body"]
    assert "Free shipping on all orders" in fields["body"]
    assert "track()" not in fields["body"] and "color:red" not in fields["body"]
    assert fields["bulk"] is True


def test_html_to_text_and_helpers():
    assert html_to_text("<p>a<br>b</p>").split() == ["a", "b"]
    assert strip_quoted("hi\n> old\nbye") == "hi\nbye"
    assert truncate("x" * 10, 4).startswith("xxxx") and "truncated" in truncate("x" * 10, 4)
    assert is_bulk({"Precedence": "bulk"}) and not is_bulk({"From": "a@b"})


def test_dedupe_across_accounts():
    emails = load_fixtures(FIXTURES, 1500)
    assert len(emails) == 5
    unique = dedupe(emails)
    assert len(unique) == 4
    assert {e.account for e in unique} == {"Gmail", "NUS"}


def test_split_bulk_keeps_school_mail_and_puts_it_first():
    personal, bulk = split_bulk(_emails(), Config().important_senders)
    assert [e.subject for e in bulk] == ["11.11 mega sale starts now!"]
    # NUS registrar newsletter is bulk but important; school senders come first.
    assert {e.subject for e in personal[:2]} == {"CS3244 Assignment 2 released", "Final exam timetable published"}
    assert len(personal) == 3


def test_graph_message_mapping():
    msg = {
        "id": "AAMk",
        "internetMessageId": "<x@nus>",
        "subject": "Exam timetable",
        "from": {"emailAddress": {"name": "Registrar", "address": "reg@nus.edu.sg"}},
        "receivedDateTime": "2026-10-26T01:00:00Z",
        "body": {"contentType": "html", "content": "<p>Finals start <b>23 Nov</b></p>"},
        "webLink": "https://outlook.office365.com/owa/?ItemID=AAMk",
        "internetMessageHeaders": [{"name": "List-Unsubscribe", "value": "<mailto:x>"}],
    }
    e = to_raw_email(msg, "NUS", 1500)
    assert e.sender == "Registrar <reg@nus.edu.sg>"
    assert e.received == datetime(2026, 10, 26, 1, tzinfo=timezone.utc)
    assert "Finals start" in e.body and "23 Nov" in e.body
    assert e.link.startswith("https://outlook")
    assert e.bulk is True


def test_prompt_wraps_emails_as_data():
    emails = _emails()
    text = _format_emails(list(enumerate(emails)))
    assert text.count("<email id=") == len(emails)
    assert 'account="NUS"' in text
    # Subject-only mode drops bodies.
    assert "Decision Trees" not in _format_emails(list(enumerate(emails)), 0)


def _fake(n, body_len):
    return [RawEmail("Gmail", f"<{i}@x>", f"subject {i}", "a@b", NOW, "word " * (body_len // 5)) for i in range(n)]


def test_budget_plan_worst_case_stays_under_budget():
    s = Summarizer("claude-sonnet-5-5", daily_budget_usd=0.065, api_key="sk-test")
    for n, body in [(5, 1500), (30, 1500), (120, 1500)]:
        emails = _fake(n, body)
        k, chars, max_out = s.plan(emails)
        assert k > 0
        prompt = _format_emails(list(enumerate(emails[:k])), chars)
        worst = ((estimate_tokens(prompt) + overhead_tokens()) * 2.00 + max_out * 10.00) / 1e6
        assert worst <= 0.065, (n, k, chars, worst)
    # Small days fit untouched.
    assert s.plan(_fake(5, 1500))[:2] == (5, None)


def test_summarizer_request_and_backfill():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        out = {"tldr": ["实习 OA 周五截止"], "items": [
            {"email_id": 0, "category": "需要行动", "priority": 1, "summary": "OA",
             "action_required": True, "action": "做 OA", "deadline": "Fri"}]}
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": json.dumps(out)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1000, "output_tokens": 200}})

    s = Summarizer("claude-sonnet-5-5", api_key="sk-test")
    s.client = anthropic.Anthropic(api_key="sk-test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    emails = _emails()
    d = s.summarize(emails)
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["thinking"] == {"type": "between_tools"}
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert sorted(it.email_id for it in d.items) == list(range(len(emails)))
    assert abs(d.cost_usd - (1000 * 2 + 200 * 10) / 1e6) < 1e-9


def test_render_groups_actions_categories_and_bulk():
    personal, bulk = split_bulk(_emails(), Config().important_senders)
    items = [
        DigestItem(email_id=i, category="课程-学校", priority=2, summary=e.subject,
                   action_required="Internship" in e.subject,
                   action="完成 OA" if "Internship" in e.subject else None,
                   deadline="Fri 30 Oct 23:59" if "Internship" in e.subject else None)
        for i, e in enumerate(personal)
    ]
    html = render_digest(Digest(tldr=["测试重点"], items=items, cost_usd=0.012), personal, bulk,
                         ["NUS 抓取失败: boom"], NOW)
    assert "测试重点" in html
    assert "需要你处理 (1)" in html and "截止 Fri 30 Oct 23:59" in html
    assert "订阅 / 推广（1 封，未经 AI）" in html and "11.11 mega sale" in html
    assert "本次 AI 成本 $0.012" in html
    assert "NUS 抓取失败: boom" in html


def test_fallback_digest_covers_every_email():
    emails = _emails()
    d = fallback_digest(emails)
    assert [it.email_id for it in d.items] == list(range(len(emails)))


def test_dry_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "digest.html"
    assert main(["--dry-run", "--no-llm", "--fixtures", str(FIXTURES), "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "每日邮件摘要" in html and "CS3244" in html
