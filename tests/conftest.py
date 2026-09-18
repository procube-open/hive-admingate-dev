import pytest

# テスト間で共有したい値（work_id など）を保持するための入れ物
@pytest.fixture(scope="session")
def shared_state():
    return {}

# ファイル単位の実行順序を固定する（ここに書いた順に実行される）
_MODULE_ORDER = [
    "test_login.py",
    "test_user.py",
    "test_group.py",
    "test_workflow.py",
    "test_connect.py"
]

def pytest_collection_modifyitems(items):
    def sort_key(item):
        filename = item.fspath.basename
        try:
            return _MODULE_ORDER.index(filename)
        except ValueError:
            # 一覧にないファイルは末尾に回す
            return len(_MODULE_ORDER)

    items.sort(key=sort_key)
