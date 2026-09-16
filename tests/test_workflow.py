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
    page.get_by_role("button", name="ワークフロー設定").click()

    # 元のタブ（page）の操作に戻る
    page.get_by_role("menuitem", name="作業申請").click()
    expect(page.get_by_role("heading", name="作業申請ガジェット")).to_be_visible()

    page.get_by_role("button", name="新規作成").click()
    expect(page.get_by_role("heading", name="作業申請ガジェット / 新規作成")).to_be_visible()

    page.locator('input[name="name"]').fill("検証作業1")
    page.locator(".MuiDataGrid-toolbar").filter(has_text="作業期間").get_by_role("button", name="追加").click()
    page.locator(".MuiDrawer-paper").get_by_role("button", name="保存").click()
    # 接続先の選択を行う
    page.locator(".MuiDataGrid-toolbar").filter(has=page.get_by_text("接続先", exact=True)).get_by_role("button", name="選択").click()
    page.get_by_role("row").filter(has_text="mock-ssh-server").get_by_role("checkbox").check()
    page.get_by_role("toolbar").get_by_role("button", name="保存").click()
    # 作業者の選択を行う
    page.locator(".MuiDataGrid-toolbar").filter(has=page.get_by_text("作業者（単体選択）", exact=True)).get_by_role("button", name="選択").click()
    page.locator('div[data-id="test-user"]').get_by_role("checkbox").check()
    page.get_by_role("toolbar").get_by_role("button", name="保存").click()
    # 管理者を選択を行う
    page.locator(".MuiDataGrid-toolbar").filter(has=page.get_by_text("管理者（単体選択） *", exact=True)).get_by_role("button", name="選択").click()
    page.locator('div[data-id="test-user"]').get_by_role("checkbox").check()
    page.get_by_role("toolbar").get_by_role("button", name="保存").click()
    page.get_by_role("button", name="保存").click()

    # 作成した作業が一覧に表示されていることを確認する
    expect(page.get_by_role("row").filter(has_text="検証作業1")).to_be_visible()
    # 作業idを取得
    work_id = page.get_by_role("row").filter(has_text="検証作業1").get_attribute("data-id")
    print(f"取得したランダムID: {work_id}")

    page.locator(f'div[data-id="{work_id}"]').get_by_role("button", name="詳細").click()
    expect(page.get_by_role("heading", name="作業申請ガジェット / 詳細")).to_be_visible()
    page.get_by_role("button", name="管理者に申請する").click()

    page.get_by_role("menuitem", name="要承認作業").click()
    expect(page.locator(f'div[data-id="{work_id}"]')).to_be_visible()
    page.locator(f'div[data-id="{work_id}"]').get_by_role("button", name="詳細").click()
    page.get_by_role("button", name="承認").click()
    page.get_by_role("button", name="発効").click()

    page.get_by_role("menuitem", name="承認済み作業").click()
    expect(page.locator(f'div[data-id="{work_id}"]')).to_be_visible()
