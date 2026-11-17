"""Ohne Netz: ein Ausfall der Dienste endet in einem Satz und nennt, wie es weitergeht."""
from urbanify import cli, survey


def test_gescheiterter_schritt_nennt_die_befehle_zum_fortsetzen(monkeypatch, capsys):
    def run(query, progress=None, **kw):
        raise survey.StepFailed("ort", "discover", RuntimeError("Overpass antwortet nicht: 504"))

    monkeypatch.setattr(survey, "run", run)
    assert cli.main(["survey", "Ort"]) == 1
    err = capsys.readouterr().err
    assert "Overpass antwortet nicht" in err and "Traceback" not in err
    assert "urbanify discover ort" in err and "urbanify locate ort" in err
    assert "urbanify zones ort" not in err      # was schon geschafft ist, wird nicht wiederholt


def test_unbekannter_ort_ist_ein_satz(monkeypatch, capsys):
    def run(query, progress=None, **kw):
        raise LookupError("Nominatim kennt keinen Ort namens 'Xyz'.")

    monkeypatch.setattr(survey, "run", run)
    assert cli.main(["survey", "Xyz"]) == 1
    assert "kennt keinen Ort" in capsys.readouterr().err
