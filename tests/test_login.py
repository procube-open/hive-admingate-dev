from playwright.sync_api import Page, expect
import pyotp

# 先ほど「スキャンできませんか？」から取得した文字列を設定
TOTP_SECRET = 'KN4U2VCKGRXG6N3HOR4GQ33YPE2XCU3T' 

def test_login(page: Page):
    # 1. ログイン画面にアクセス
    page.goto("https://idm3.admingate-dev.procube-demo.jp/")
    
    # 2. IDを入力して次へ
    page.locator("#username").fill("test-user")
    page.locator("#kc-login").click()
    
    # 3. パスワードを入力して次へ
    page.locator("#password").fill("P6bjY2baF(eR")
    page.locator("#kc-login").click()

    # 4. ワンタイムパスワードの入力
    totp = pyotp.TOTP(TOTP_SECRET)
    # ※ワンタイムコード入力欄の実際のID名（例: #totp）に置き換えてください
    page.locator("#otp").fill(totp.now())
    page.locator("#kc-login").click() # 認証ボタンのIDに合わせて変更してください

    # 5. ログイン完了の検証（ロゴが表示されるまで自動待機して確認）
    expect(page.get_by_alt_text("Logo")).to_be_visible()

    page.context.storage_state(path="state.json")
