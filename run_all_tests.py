import sys
import subprocess
from pathlib import Path

def run_with_venv():
    """Run the tests using the virtual environment"""
    venv_python = Path('.venv/bin/python3')
    if venv_python.exists():
        print("🔧 仮想環境でテストを実行中...")
        # Use pytest to run tests
        result = subprocess.run([
            str(venv_python), '-m', 'pytest', 'test/'
        ], cwd='.')
        return result.returncode
    else:
        print("❌ 仮想環境が見つかりません。テストを実行できません。")
        sys.exit(1)

if __name__ == '__main__':
    sys.exit(run_with_venv())