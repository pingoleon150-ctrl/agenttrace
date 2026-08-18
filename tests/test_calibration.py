from agenttrace.calibration import CalibrationProfile, fit_presence_likelihood_ratios
from agenttrace.models import Signal


def test_presence_lr_prefers_positive_specific_signal():
    ratios = fit_presence_likelihood_ratios(
        [("pos", {"rare"}), ("pos", {"rare"}), ("neg", {"common"}), ("benign", set())]
    )
    assert ratios["rare"] > 1
    assert ratios["common"] < 1


def test_profile_combines_log_likelihood_ratios():
    profile = CalibrationProfile({"one": 10.0, "two": 5.0}, prior_probability=0.1)
    signals = [
        Signal(family="artifact", name="one", score=0.9),
        Signal(family="semantic", name="two", score=0.9),
    ]
    log_lr, posterior, reasons = profile.evidence(signals)
    assert log_lr > 3.9
    assert posterior > 0.8
    assert len(reasons) == 2
