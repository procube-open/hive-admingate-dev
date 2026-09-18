# test_group.py
import pytest
from playwright.sync_api import Page, expect

@pytest.fixture
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "storage_state": "state.json",
    }

def test_dashboard_menu(page: Page):
    page.goto("https://idm3.admingate-dev.procube-demo.jp/")

    # 認証設定ボタンをクリック
    page.get_by_role("button", name="認証設定").click()

    # 元のタブ（page）の操作に戻る
    page.get_by_role("menuitem", name="チーム編集").click()
    expect(page.get_by_role("heading", name="チームガジェット")).to_be_visible()

    page.get_by_role("button", name="追加").click()
    expect(page.get_by_role("heading", name="チームガジェット / 新規作成")).to_be_visible()

    page.locator('input[name="id"]').fill("testgroup1")
    page.locator('input[name="name"]').fill("テストチーム")
    page.get_by_role("button", name="選択").click()
    page.locator('div[data-id="test-user"]').get_by_role("checkbox").check()
    page.get_by_role("toolbar").get_by_role("button", name="保存").click()
    page.get_by_role("button", name="保存").click()
    page.get_by_role("button", name="発効").click()

    # test-group1 の行が存在（表示）しているか検証する
    expect(page.locator('[data-id="testgroup1"]')).to_be_visible()

    # test-user1の行（親要素）を探し、その中にある「編集」ボタンをクリックする
    page.locator('[data-id="testgroup1"]').get_by_role("button", name="編集").click()
    page.get_by_role("button", name="削除").click()
    page.get_by_role("button", name="削除").click()
    page.get_by_role("button", name="発効").click()

    # test-user1 の行が存在しない（消えた）ことを検証する
    expect(page.locator('[data-id="testgroup1"]')).not_to_be_visible()
