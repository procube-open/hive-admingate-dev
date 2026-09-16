# test_user.py
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
    page.get_by_role("menuitem", name="ユーザ編集").click()
    expect(page.get_by_role("heading", name="ユーザガジェット")).to_be_visible()

    page.get_by_role("button", name="追加").click()
    expect(page.get_by_role("heading", name="ユーザガジェット / 新規作成")).to_be_visible()

    page.locator('input[name="uid"]').fill("test-user1")
    page.locator('input[name="sn"]').fill("テスト")
    page.locator('input[name="cn"]').fill("ユーザ")
    page.locator("#mui-component-select-idmRole").click()
    page.get_by_role("option", name="利用者").click()
    page.get_by_role("button", name="選択").click()
    # data-id="procube" を持つ要素（行）の中にあるチェックボックスをチェックする
    page.locator('div[data-id="procube"]').get_by_role("checkbox").check()
    # 「データグリッドのツールバー」の中にある「保存」ボタンに絞り込む
    page.locator(".MuiDataGrid-toolbar").get_by_role("button", name="保存").click()
    page.locator('input[name="email"]').fill("test@procube.jp")
    # 特徴的なクラス名「refine-save-button」を直接狙い撃ちする
    page.get_by_role("button", name="保存").click()
    page.get_by_role("button", name="発行").click()

    # test-user1 の行が存在（表示）しているか検証する
    expect(page.locator('[data-id="test-user1"]')).to_be_visible()

    # test-user1の行（親要素）を探し、その中にある「編集」ボタンをクリックする
    page.locator('[data-id="test-user1"]').get_by_role("button", name="編集").click()
    page.get_by_role("button", name="削除").click()
    page.get_by_role("button", name="発行").click()

    # test-user1 の行が存在しない（消えた）ことを検証する
    expect(page.locator('[data-id="test-user1"]')).not_to_be_visible()
