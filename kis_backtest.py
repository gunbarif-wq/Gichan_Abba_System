#!/usr/bin/env python3
"""KIS API 실제 연동 - 지난주 데이터 백테스팅"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class KISAPIClient:
    def __init__(self):
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.app_key = os.getenv('KIS_APP_KEY')
        self.app_secret = os.getenv('KIS_APP_SECRET')
        self.access_token = None
        
        if not all([self.app_key, self.app_secret]):
            raise ValueError("KIS_APP_KEY, KIS_APP_SECRET이 .env 파일에 없습니다")
    
    def get_access_token(self):
        try:
            url = f"{self.base_url}/oauth2/tokenP"
            headers = {"content-type": "application/json"}
            body = {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret
            }
            
            response = requests.post(url, headers=headers, data=json.dumps(body))
            
            if response.status_code == 200:
                result = response.json()
                self.access_token = result.get('access_token')
                logger.info("✅ KIS API 토큰 발급 완료")
                return True
            else:
                logger.error(f"❌ 토큰 발급 실패: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ 토큰 발급 오류: {str(e)}")
            return False
    
    def get_daily_price(self, symbol, start_date, end_date):
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.access_token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST03010100"
            }
            
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": symbol,
                "fid_input_date_1": start_date,
                "fid_input_date_2": end_date,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('rt_cd') == '0':
                    data = result.get('output2', [])
                    logger.info(f"✅ {len(data)}일 데이터 조회 완료")
                    return self._parse_price_data(data)
                else:
                    logger.error(f"❌ 데이터 조회 실패: {result.get('msg1')}")
                    return None
            else:
                logger.error(f"❌ API 호출 실패: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"❌ 데이터 조회 오류: {str(e)}")
            return None
    
    def _parse_price_data(self, data):
        parsed = []
        for item in data:
            try:
                parsed.append({
                    'date': item['stck_bsop_date'],
                    'open': int(item['stck_oprc']),
                    'high': int(item['stck_hgpr']),
                    'low': int(item['stck_lwpr']),
                    'close': int(item['stck_clpr']),
                    'volume': int(item['acml_vol'])
                })
            except (KeyError, ValueError):
                continue
        parsed.sort(key=lambda x: x['date'])
        return parsed


def get_last_week_dates():
    today = datetime.now()
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    last_monday = this_monday - timedelta(days=7)
    last_friday = last_monday + timedelta(days=4)
    
    start_date = last_monday.strftime('%Y%m%d')
    end_date = last_friday.strftime('%Y%m%d')
    
    logger.info(f"📅 백테스팅 기간: {last_monday.strftime('%Y-%m-%d')} ~ {last_friday.strftime('%Y-%m-%d')}")
    return start_date, end_date


def calculate_pnl(data, quantity=10):
    if not data or len(data) == 0:
        return None
    
    buy_price = data[0]['open']
    buy_amount = buy_price * quantity
    sell_price = data[-1]['close']
    sell_amount = sell_price * quantity
    
    commission_rate = 0.00015
    buy_commission = buy_amount * commission_rate
    sell_commission = sell_amount * commission_rate
    total_commission = buy_commission + sell_commission
    
    tax_rate = 0.0018
    tax = sell_amount * tax_rate
    
    gross_profit = sell_amount - buy_amount
    net_profit = gross_profit - total_commission - tax
    profit_ratio = (net_profit / buy_amount) * 100
    
    return {
        'buy_date': data[0]['date'],
        'sell_date': data[-1]['date'],
        'buy_price': buy_price,
        'sell_price': sell_price,
        'quantity': quantity,
        'buy_amount': buy_amount,
        'sell_amount': sell_amount,
        'total_commission': total_commission,
        'tax': tax,
        'net_profit': net_profit,
        'profit_ratio': profit_ratio,
    }


def print_report(data, pnl):
    logger.info("\n" + "="*70)
    logger.info("📊 백테스팅 결과 - 삼성전자 (005930)")
    logger.info("="*70)
    logger.info(f"기간: {pnl['buy_date']} ~ {pnl['sell_date']}\n")
    
    logger.info(f"매수: {pnl['buy_date']} 시가 {pnl['buy_price']:,}원 × {pnl['quantity']}주 = {pnl['buy_amount']:,}원")
    logger.info(f"매도: {pnl['sell_date']} 종가 {pnl['sell_price']:,}원 × {pnl['quantity']}주 = {pnl['sell_amount']:,}원")
    logger.info(f"\n수수료: {pnl['total_commission']:,.0f}원 | 거래세: {pnl['tax']:,.0f}원")
    
    profit_sign = "+" if pnl['net_profit'] >= 0 else ""
    logger.info(f"\n순손익: {profit_sign}{pnl['net_profit']:,.0f}원 ({profit_sign}{pnl['profit_ratio']:.2f}%)")
    logger.info("="*70 + "\n")
    
    week_high = max([d['high'] for d in data])
    week_low = min([d['low'] for d in data])
    logger.info(f"주간 최고: {week_high:,}원 | 최저: {week_low:,}원 | 변동폭: {week_high-week_low:,}원")


def main():
    logger.info("="*70)
    logger.info("Gichan Abba System - 지난주 실제 데이터 백테스팅")
    logger.info("="*70 + "\n")
    
    try:
        logger.info("[Step 1] KIS API 연결 중...")
        client = KISAPIClient()
        
        if not client.get_access_token():
            logger.error("토큰 발급 실패")
            return
        
    except ValueError as e:
        logger.error(f"❌ {str(e)}")
        return
    
    logger.info("\n[Step 2] 백테스팅 기간 계산...")
    start_date, end_date = get_last_week_dates()
    
    logger.info("\n[Step 3] 삼성전자 데이터 조회 중...")
    data = client.get_daily_price("005930", start_date, end_date)
    
    if not data:
        logger.error("❌ 데이터 조회 실패")
        return
    
    if len(data) == 0:
        logger.warning("⚠️ 데이터가 없습니다 (휴장일)")
        return
    
    logger.info("\n[Step 4] 손익 계산...")
    pnl = calculate_pnl(data, quantity=10)
    
    print_report(data, pnl)
    logger.info("✅ 백테스팅 완료!\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"❌ 오류: {str(e)}")
        sys.exit(1)