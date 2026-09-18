# test_connect.py
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

    work_link = page.locator('a[href="/works"]')
    expect(work_link).to_be_visible(timeout=60_000)
    work_link.click()
    expect(page).to_have_url("https://admingate-core.admingate-dev.procube-demo.jp/works")

    work_row = page.locator(f'tr[data-id="{shared_state["work_id"]}"]')
    expect(work_row).to_be_visible()
    work_row.locator("button").first.click()

    connection_row = page.get_by_role("row").filter(has_text="mock-ssh-server")
    expect(connection_row).to_be_visible()
    connection_row.get_by_role("button", name="接続").click()

    page.wait_for_timeout(60_000)
    disconnected_dialog = (
        page.get_by_role("dialog")
        .filter(has=page.get_by_role("heading", name="接続が切断されました"))
        .filter(has_text="接続エラーが発生しました。")
    )
    expect(disconnected_dialog).not_to_be_visible()
    
