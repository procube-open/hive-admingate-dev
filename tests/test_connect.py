# test_connect.py
import re

import pytest
from playwright.sync_api import Page, expect

@pytest.fixture
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "storage_state": "state.json",
    }

def test_dashboard_menu(page: Page, shared_state):
    page.goto("https://admingate-core.admingate-dev.procube-demo.jp/")

    # test_workflow.py の直後実行では反映に 20〜60 秒程度かかることがあるため
    # ここで余裕を持って待機してから、対象の作業が一覧に出るまで確認する
    page.wait_for_timeout(60_000)

    work_link = page.locator('a[href="/works"]')
    expect(work_link).to_be_visible(timeout=60_000)
    work_link.click()
    expect(page).to_have_url(
        re.compile(r"^https://admingate-core\.admingate-dev\.procube-demo\.jp/works(?:\?.*)?$")
    )

    work_id = shared_state.get("work_id")
    if work_id:
        work_row = page.get_by_role("row").filter(has_text=work_id).first
    else:
        work_row = page.get_by_role("row").filter(has_text="20260915検証作業1").first
        if page.get_by_role("row").filter(has_text="20260915検証作業1").count() == 0:
            work_row = page.get_by_role("row").filter(has_text="検証作業1").first

    expect(work_row).to_be_visible(timeout=60_000)
    work_row.locator("button").first.click()

    expect(page).to_have_url(re.compile(r"^https://admingate-core\.admingate-dev\.procube-demo\.jp/works/.+/targets(?:\?.*)?$"))

    connection_row = page.get_by_role("row").filter(has_text="mock-ssh-server").first
    expect(connection_row).to_be_visible(timeout=60_000)
    connection_row.get_by_role("button", name=re.compile(r"Connect", re.IGNORECASE)).click()

    page.wait_for_timeout(60_000)
    disconnected_dialog = (
        page.get_by_role("dialog")
        .filter(has=page.get_by_role("heading", name="接続が切断されました"))
        .filter(has_text="接続エラーが発生しました。")
    )
    expect(disconnected_dialog).not_to_be_visible()
    
