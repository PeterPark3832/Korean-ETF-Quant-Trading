"""
run_bot.py 환경변수 검증 로직(_validate_env) 단위 테스트
"""
import pytest

from run_bot import _validate_env


class TestValidateEnv:
    def test_paper_mode_skips_validation(self, monkeypatch):
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        _validate_env("paper")  # 예외/종료 없이 통과해야 함

    @pytest.mark.parametrize("mode", ["kis_paper", "kis_real"])
    def test_kis_mode_missing_keys_exits(self, monkeypatch, mode):
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            _validate_env(mode)
        assert exc_info.value.code == 1

    @pytest.mark.parametrize("mode", ["kis_paper", "kis_real"])
    def test_kis_mode_with_all_keys_passes(self, monkeypatch, mode):
        monkeypatch.setenv("KIS_APP_KEY", "key")
        monkeypatch.setenv("KIS_APP_SECRET", "secret")
        monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")
        _validate_env(mode)  # 예외/종료 없이 통과해야 함

    def test_kis_mode_partial_keys_exits(self, monkeypatch):
        monkeypatch.setenv("KIS_APP_KEY", "key")
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        with pytest.raises(SystemExit):
            _validate_env("kis_real")
