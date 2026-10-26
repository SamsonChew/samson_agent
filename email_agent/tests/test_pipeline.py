from datetime import datetime, timezone
from pathlib import Path

from email_agent.main import load_fixtures, main
from email_agent.parser import html_to_text, parse_mime, strip_quoted, truncate
from email_agent.render import render_digest
from email_agent.sources import dedupe
from email_agent.sources.graph_source import to_raw_email
from email_agent.summarizer import Digest, DigestItem, _format_emails, fallback_digest

FIXTURES = Path(__file__).parent / "fixtures"


def test_plain_text_drops_quoted_reply():
    fields = parse_mime((FIXTURES / "gmail/01_internship.eml").read_bytes())
    assert fields["subject"] == "Quant Research Internship - next round"
    assert "Fri 30 Oct 23:59" in fields["body"]
    assert "attached is my CV" not in fields["body"]
    assert "wrote:" not in fields["body"]
    assert fields["received"].tzinfo is not None


def test_html_part_is_converted_and_scripts_removed():
    body = parse_mime((FIXTURES / "gmail/02_promo.eml").read_bytes())["body"]
    assert "Up to 90% off" in body
    assert "Free shipping on all orders" in body
    assert "track()" not in body and "color:red" not in body


def test_html_to_text_and_helpers():
    assert html_to_text("<p>a<br>b</p>").split() == ["a", "b"]
    assert strip_quoted("hi\n> old\nbye") == "hi\nbye"
    assert truncate("x" * 10, 4).startswith("xxxx") and "truncated" in truncate("x" * 10, 4)


def test_dedupe_across_accounts():
    emails = load_fixtures(FIXTURES, 4000)
    assert len(emails) == 4
    unique = dedupe(emails)
    assert len(unique) == 3
    assert {e.account for e in unique} == {"Gmail", "NUS"}


def test_graph_message_mapping():
    msg = {
        "id": "AAMk",
        "internetMessageId": "<x@nus>",
        "subject": "Exam timetable",
        "from": {"emailAddress": {"name": "Registrar", "address": "reg@nus.edu.sg"}},
        "receivedDateTime": "2026-10-26T01:00:00Z",
        "body": {"contentType": "html", "content": "<p>Finals start <b>23 Nov</b></p>"},
        "webLink": "https://outlook.office365.com/owa/?ItemID=AAMk",
    }
    e = to_raw_email(msg, "NUS", 4000)
    assert e.sender == "Registrar <reg@nus.edu.sg>"
    assert e.received == datetime(2026, 10, 26, 1, tzinfo=timezone.utc)
    assert "Finals start" in e.body and "23 Nov" in e.body
    assert e.link.startswith("https://outlook")


def test_prompt_wraps_emails_as_data():
    emails = dedupe(load_fixtures(FIXTURES, 4000))
    text = _format_emails(list(enumerate(emails)))
    assert text.count("<email id=") == len(emails)
    assert 'account="NUS"' in text


def test_render_groups_actions_and_categories():
    emails = dedupe(load_fixtures(FIXTURES, 4000))
    items = [
        DigestItem(email_id=i, category="推广" if "sale" in e.subject else "课程-学校", priority=2,
                   summary=e.subject, action_required="Internship" in e.subject,
                   action="完成 OA" if "Internship" in e.subject else None,
                   deadline="Fri 30 Oct 23:59" if "Internship" in e.subject else None)
        for i, e in enumerate(emails)
    ]
    html = render_digest(Digest(tldr=["测试重点"], items=items), emails, ["NUS 抓取失败: boom"],
                         datetime(2026, 10, 26, 7, tzinfo=timezone.utc))
    assert "测试重点" in html
    assert "需要你处理 (1)" in html and "截止 Fri 30 Oct 23:59" in html
    assert "已折叠 1 封推广邮件" in html
    assert "NUS 抓取失败: boom" in html


def test_fallback_digest_covers_every_email():
    emails = dedupe(load_fixtures(FIXTURES, 4000))
    d = fallback_digest(emails)
    assert [it.email_id for it in d.items] == list(range(len(emails)))


def test_dry_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "digest.html"
    assert main(["--dry-run", "--no-llm", "--fixtures", str(FIXTURES), "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "每日邮件摘要" in html and "CS3244" in html
