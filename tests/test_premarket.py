from datetime import datetime,timezone
import unittest
from screener.premarket import parse_quote,parse_news,collect,MARKETS


class PremarketTests(unittest.TestCase):
    def payload(self):
        stamps=[datetime(2026,10,d,13,30,tzinfo=timezone.utc).timestamp() for d in (23,26)]
        return {'chart':{'result':[{'meta':{'symbol':'^GSPC','regularMarketTime':datetime(2026,10,26,15,tzinfo=timezone.utc).timestamp(),'regularMarketPrice':115},
                'timestamp':stamps,'indicators':{'quote':[{'close':[100,110]}]}}]}}

    def test_preopen_excludes_unfinished_session_and_latest_has_real_quote_time(self):
        cutoff=datetime(2026,10,26,16,tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError,'不足兩次'):
            parse_quote(self.payload(),MARKETS[0],cutoff)
        late=datetime(2026,10,27,0,tzinfo=timezone.utc)
        result=parse_quote(self.payload(),MARKETS[0],late,'latest')
        self.assertEqual(result['previous_close'],100)
        self.assertEqual(result['close'],115)
        self.assertIsNotNone(result['quoted_at'])

    def test_no_fake_values_on_transport_failure(self):
        def unavailable(url):raise OSError('source unavailable')
        result=collect(datetime(2026,10,27,tzinfo=timezone.utc),unavailable,'latest')
        self.assertEqual(result['status'],'error')
        self.assertTrue(all(m['status']=='error' and 'close' not in m for m in result['markets']))
        self.assertEqual(result['news'],{'台灣':[],'國際':[]})

    def test_news_time_window_and_unsafe_source(self):
        now=datetime(2026,10,27,tzinfo=timezone.utc)
        template='<rss><channel><item><title>Fed CPI update</title><link>{url}</link><pubDate>{date}</pubDate></item></channel></rss>'
        result=parse_news(template.format(url='https://example.org/news',date='Mon, 26 Oct 2026 20:00:00 GMT').encode(),'test','國際',now)
        self.assertEqual(len(result),1)
        self.assertEqual(parse_news(template.format(url='https://example.org/news',date='Tue, 27 Oct 2026 02:00:00 GMT').encode(),'test','國際',now),[])
        with self.assertRaises(ValueError):parse_news(template.format(url='javascript:alert(1)',date='Mon, 26 Oct 2026 20:00:00 GMT').encode(),'test','國際',now)
        with self.assertRaises(ValueError):parse_news(b'<!DOCTYPE rss><rss/>','test','國際',now)
