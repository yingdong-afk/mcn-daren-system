import pytest

from domain import numeric, read_import, score_talent, validate_talent


@pytest.mark.parametrize('value', ['-1', 'NaN', 'Infinity', '1000000000001', '1.5', '不是数字'])
def test_invalid_fans(value):
    with pytest.raises(ValueError):
        numeric(value, '粉丝数量')


def test_money_precision_and_unknown():
    assert numeric('0', '金额', money=True) == 0
    assert numeric('10.01', '金额', money=True) == 1001
    assert numeric('', '金额', money=True) is None
    with pytest.raises(ValueError):
        numeric('1.001', '金额', money=True)


def test_requires_sales_period():
    with pytest.raises(ValueError, match='统计周期'):
        validate_talent({'nickname': '测试', 'douyin_id': 'test', 'historical_gmv': '0'})


def test_missing_does_not_become_zero_score():
    talent = dict(fans=None, categories='', content_types='', historical_gmv_cents=None, sales_period='')
    product = dict(min_fans=100, max_fans=1000, target_gmv_cents=10000, category='测试类目', content_type='测试内容', sales_period='测试周期')
    score = score_talent(talent, product)
    assert score['total'] is None and score['coverage'] == 0
    assert all(d['points'] is None for d in score['dimensions'])


def test_zero_sales_is_known_and_scores_are_bounded():
    talent = dict(fans=50, categories='其他类目', content_types='其他内容', historical_gmv_cents=0, sales_period='测试周期')
    product = dict(min_fans=100, max_fans=1000, target_gmv_cents=10000, category='测试类目', content_type='测试内容', sales_period='测试周期')
    assert score_talent(talent, product)['total'] == 12.5
    talent.update(fans=2000, historical_gmv_cents=200000)
    assert score_talent(talent, product)['total'] == 37.5


def test_import_header_encoding_and_limits():
    content = '达人昵称,抖音号\n测试,test_gb\n'.encode('gb18030')
    assert read_import(content, 'input.csv')[0][1]['nickname'] == '测试'
    for content in ['姓名,账号\n', '达人昵称,抖音号,抖音号\n', '达人昵称,抖音号,陌生列\n', '达人昵称,抖音号\n测试,test,extra\n']:
        with pytest.raises(ValueError):
            read_import(content.encode(), 'input.csv')
    with pytest.raises(ValueError, match='5000'):
        read_import(('达人昵称,抖音号\n' + '测试,test\n'*5001).encode(), 'input.csv')
