from datetime import date
import pytest
from garage.calculator import Rule,Service,calculate

TODAY=date(2026,10,9)
def due(rule,**kw):
    params=dict(today=TODAY,miles=50000,in_service=date(2021,1,1),services=[Service(date(2026,7,1),45000)])
    params.update(kw);return calculate(rule,**params)

@pytest.mark.parametrize('miles,status',[(49999,'upcoming'),(50500,'due-soon'),(51000,'due'),(51001,'overdue')])
def test_mileage_boundary(miles,status):
    assert due(Rule(miles=6000,basis='service'),miles=miles).status==status

@pytest.mark.parametrize('today,status',[(date(2026,11,30),'upcoming'),(date(2026,12,2),'due-soon'),(date(2027,1,1),'due'),(date(2027,1,2),'overdue')])
def test_time_boundary(today,status):
    assert due(Rule(months=6,basis='service'),today=today).status==status

def test_whichever_first():
    assert due(Rule(miles=6000,months=3,basis='service')).status=='overdue'

def test_unknown_history_never_assumes_completed():
    assert due(Rule(miles=6000,months=6),services=[]).status=='unknown'

def test_factory_original_first_and_subsequent_coolant():
    rule=Rule(miles=75000,months=72,first_miles=137500,first_months=132,basis='service')
    first=due(rule,services=[],never_serviced=True)
    assert first.miles==137500 and first.date==date(2032,1,1)
    subsequent=due(rule,services=[Service(date(2026,1,2),130000)],miles=140000)
    assert subsequent.miles==205000 and subsequent.date==date(2032,1,2)

def test_milestones_do_not_drift():
    result=due(Rule(miles=30000,months=30),services=[Service(date(2026,2,1),32000)])
    assert result.miles==60000 and result.date==date(2028,7,1)

def test_missing_time_baseline_does_not_hide_known_overdue():
    result=due(Rule(miles=6000,months=6),in_service=None,miles=55000)
    assert result.status=='overdue' and result.unknown

def test_missing_time_baseline_is_not_healthy():
    result=due(Rule(miles=6000,months=6),in_service=None,miles=46000)
    assert result.status=='unknown'

def test_month_end_leap_year():
    result=due(Rule(months=1,basis='service'),today=date(2024,2,1),services=[Service(date(2024,1,31),10)])
    assert result.date==date(2024,2,29)

def test_backdated_record_is_not_latest():
    result=due(Rule(miles=6000,basis='service'),services=[Service(date(2026,7,1),45000),Service(date(2026,1,1),20000)])
    assert result.miles==51000

def test_engine_hours():
    rule=Rule(miles=5000,months=6,hours=200,basis='service')
    assert due(rule,engine_hours=None).unknown
    result=due(rule,miles=45001,services=[Service(date(2026,7,1),45000,1000)],engine_hours=1201)
    assert result.status=='overdue' and result.remaining_hours==-1

def test_conditional_has_no_invented_interval():
    result=due(Rule(basis='conditional'))
    assert result.status=='as-needed' and result.date is None and result.miles is None
