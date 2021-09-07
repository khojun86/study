# from pyupbit import WebSocketManager, pd
import pyupbit
import time
import websockets
# import telegram
import asyncio
import json
import numpy as np
import os, sys
import schedule
import pprint


def cal_margin():
    df = pyupbit.get_ohlcv(ticker, interval="minute60", count=10)
    lastlow = np.array(df['low'].tolist())
    nexthigh = np.array(df['high'].tolist())
    nexthigh = nexthigh[1:len(nexthigh)]
    lastlow = lastlow[0:len(lastlow) - 1]
    range = (nexthigh - lastlow) / lastlow * 100
    df = pyupbit.get_ohlcv(ticker, count=1)
    # dayrange = np.array((df['high'] - df['low']) / df['low'])
    dayrange = df['open']/df['low']
    margin=float(np.mean(range) / 3.5) + dayrange[-1] / 3.5
    # print('margin =', margin)
    return margin


async def upbit_ws_client(ticker):
    url = "wss://api.upbit.com/websocket/v1"
    prevTime = '';buyTime = time.strftime('%H:%M')
    tickprice = np.array([])
    # tickgroup = 30
    firstbuyprice = 6500  ### 0907 update
    buyprice = firstbuyprice;sellprice = 0
    boughtedbalance = 0;boughtedvolume = 0
    grouptickclose = np.array([])
    state = 'none';selluuid = ''
    # 초기 설정
    init_balance = upbit.get_balance("KRW")
    init_volume = float(upbit.get_balances()[1]['locked']) + float(upbit.get_balances()[1]['balance'])
    #### telegram alarm ####
    # print("init_balance =", init_balance, "\ninit_volume =", init_volume)
    ####  ohlcv 변동 폭 계산 ####
    # df = pyupbit.get_ohlcv(ticker, interval="minute60", count=10)
    # lastlow = np.array(df['low'].tolist())
    # nexthigh = np.array(df['high'].tolist())
    # # print(nexthigh[1:len(nexthigh)]);print(lastlow[0:len(nexthigh)-1])
    # nexthigh = nexthigh[1:len(nexthigh)]
    # lastlow = lastlow[0:len(lastlow) - 1]
    # # print((nexthigh-lastlow)/lastlow*100)
    # range = (nexthigh - lastlow) / lastlow * 100
    # df = pyupbit.get_ohlcv(ticker, count=1)
    # # pprint.pprint(df)
    # # print(df['high'],df['low'],(df['high']-df['low'])/df['low'])
    # dayrange = np.array((df['high'] - df['low']) / df['low'])
    margin = cal_margin()
    ## tic 판단
    close = pyupbit.get_current_price(ticker)
    if close > 2000000:
        tic = 1000
    elif close > 1000000:
        tic = 500
    elif close > 500000:
        tic = 100
    elif close > 100000:
        tic = 50
    elif close > 10000:
        tic = 10
    elif close > 1000:
        tic = 5
    elif close > 100:
        tic = 1
    elif close > 10:
        tic = 0.1
    else:
        tic = 0.01

    bbl_last = 0;bbl = 0

    ## 초기 주문 있을 때 대응
    init_order = upbit.get_order(ticker)
    if len(init_order) != 0:
        # print(init_order[0])
        remains = upbit.get_balances()[1]
        ordered_abp = remains['avg_buy_price']
        ordered_volume = remains['locked']
        ordered_totalbalance = float(ordered_abp) * float(ordered_volume)
        # print(ordered_abp,ordered_volume,ordered_totalbalance)
        upbit.cancel_order(init_order[0]['uuid'])
        time.sleep(1)
        boughtedbalance = ordered_totalbalance
        boughtedvolume = ordered_volume
        tmpsellprice = int(ordered_abp * (1 + margin / 100) / tic) * tic
        sellorder = upbit.sell_limit_order(ticker, tmpsellprice, boughtedvolume)
        time.sleep(2)
        selluuid = sellorder['uuid']
    ## 초기 volume 있을 때 대응
    if init_volume > 0.001:
        remains = upbit.get_balances()[1]
        ordered_abp = remains['avg_buy_price']
        boughtedvolume = init_volume
        boughtedbalance = float(ordered_abp) * float(boughtedvolume)

    async with websockets.connect(url) as websocket:
        subscribe_fmt = [{"ticket": "test00"}, {"type": "trade", "codes": [ticker], "isOnlyRealtime": True}]
        # ,{"format":"SIMPLE"}
        subscribe_data = json.dumps(subscribe_fmt)
        await websocket.send(subscribe_data)
        while True:
            try:
                data = await websocket.recv()

                data = json.loads(data)
                # print(data)
                ##### 30 tic close : tickprice[tickgroup-1] ####
                # if len(tickprice) < tickgroup:
                if len(tickprice) < 30:
                    tickprice = np.append(tickprice, [data["trade_price"]])
                ##### grouptickclose for ma caculation ####
                else:
                    if len(grouptickclose) < 65:
                        grouptickclose = np.append(grouptickclose, [data["trade_price"]])
                    else:
                        grouptickclose = grouptickclose[1:65]
                        grouptickclose = np.append(grouptickclose, [data["trade_price"]])
                    tickprice = np.array([])

                nowTime = time.strftime('%H:%M')
                #### 0817 update 매도 가 이상 도달 시
                if sellprice != 0 and data["trade_price"] > sellprice:
                    ### 0907 update 손익 계산 ### // 수수료는 이담에 생각해보자
                    boughtedprice=abp*boughtedvolume
                    selledprice=sellprice*boughtedvolume
                    gain=sellprice-boughtedprice

                    boughtedbalance = 0
                    boughtedvolume = 0
                    sellprice = 0
                    selluuid = ''
                    buyprice = firstbuyprice
                    abp = 0
                    ####0831 update abp 초기화 ####
                    init_balance = balance
                    init_volume = upbit.get_balance(ticker)
                    print("매도확인 =\033[31m", init_balance,"\033[0m","손익 =\033[31m",gain,"\033[0m")

                    #### telegram alarm ####
                    ## bot.sendMessage(chat_id=tlgm_id, text='현재' + str(init_balance))

                if nowTime != prevTime:
                    df = pyupbit.get_ohlcv(ticker, 'minute1')
                    df_close = df['close']

                    #### minute candle moving average ####
                    roll_ma20 = df_close.rolling(20)
                    minute_ma20 = roll_ma20.mean()

                    balance = upbit.get_balance("KRW")

                    #### bollinger band coefficient = 2.32 #### 0907 update
                    # bbl_last = bbl

                    bbm = minute_ma20[199]
                    bbl = bbm - roll_ma20.std()[199] * 2.32
                    # bbu = bbm + roll_ma20.std()[
                    #     199] * 2.4  # print(round(bbl, 0), round(bbm, 0));print("BB 하단",round(bbl, 0))


                #### 현재가가 BB low 아래에 있을 때 매수 결정 ####
                if data["trade_price"] < bbl and state == 'none' and balance >= buyprice and len(
                        grouptickclose) == 65 and nowTime != buyTime:
                    state = 'ready'
                    if balance != init_balance:
                        ####0831 update 매수 수량 결정, 현재가가 abp 보다 낮으면 비율*5####
                        if abp > data["trade_price"]:
                            priceratio = abs(abp / data["trade_price"] - 1) * 5 + 1
                            buyprice = int(buyprice * priceratio)
                        else:
                            buyprice = firstbuyprice
                    if sellprice != 0:
                        selluuid = sellorder['uuid']
                        # print('sell order =', selluuid)
                    print(time.strftime('%H:%M'), buyprice, "원")
                #### 30tick close 의 ma 5 가 ma 50 을 돌파할 때 매수####  ## 0831 update
                if state == 'ready':
                    tick30_ma35 = grouptickclose[30:65].mean()
                    # tick30_ma10last = grouptickclose[54:64].mean()
                    tick30_ma5 = grouptickclose[60:65].mean()  # ;print(state)
                    if tick30_ma35 < tick30_ma5: # and np.isnan(tick30_ma50) == False: 0901 update
                        print(time.strftime('%H:%M'), '매수주문')
                        buy = upbit.buy_market_order(ticker, buyprice)
                        state = 'buy'
                        # buyTime = time.strftime('%H:%M')
                        # print(buyTime, state)
                #### 매수 한 다음 1분 중 매도가 결정 매도주문 ####
                if state == 'buy' and nowTime != prevTime:
                    state = 'none'
                    # print(state)
                    boughtedbalance += buyprice
                    # print(boughtedbalance)
                    boughtedvolume = float(upbit.get_balances()[1]['locked']) + float(
                        upbit.get_balances()[1]['balance'])
                    # print(boughtedvolume)
                    abp = boughtedbalance / boughtedvolume
                    print('매수총액 =', round(boughtedbalance,2), '보유수량 =', round(boughtedvolume, 2), '평단가 =',
                          round(abp, 2))
                    # print('판매가 =', sellprice)
                    if sellprice == 0:
                        sellprice = int(abp * (1 + margin / 100) / tic) * tic
                    else:
                        upbit.cancel_order(selluuid)
                        time.sleep(2)
                        sellprice = int(abp * (1 + margin / 100) / tic) * tic
                        time.sleep(2)
                    # print(time.strftime('%H:%M'), "매도가 ABP+", margin, "% = ", sellprice)
                    sellorder = upbit.sell_limit_order(ticker, sellprice, boughtedvolume)
                    time.sleep(2)
                    selluuid = sellorder['uuid']
                    # pprint.pprint(sellorder)

                if nowTime != prevTime:

                    #### 0817 update 매도 주문 exception 발생 안함
                    #### 각 pyupbit method call 시 간격이 필수
                    prevTime = nowTime
                    margin=cal_margin()
            except Exception as e:
                print('힝')
                #### 0907 update ####
                #### 혹시라도 1006 터지면 재시작하기####
                sys.stdout.flush()
                os.execv(sys.argv[0], sys.argv)


async def main(ticker):
    await upbit_ws_client(ticker)


ticker = "KRW-ETC"
access_key = "GFexnbUxVxmu1ClL5oNaedEdGYwX4ZSzdcwn0806"
secret_key = "TS2cSWkl0vUkwGgmxQmyCdgeLydxNBlYacbowHp5"

upbit = pyupbit.Upbit(access_key, secret_key)
balance = upbit.get_balance("KRW")
print("init_balance =\033[31m", balance, "\033[0m")

# 텔레그램 연결
# tlgm_token = '1733326409:AAFVLFVWG2nPJcP65YcglWgQKeKLQtJuzE4'
# tlgm_id = '1758620562'
# bot = telegram.Bot(token=tlgm_token)
# updates = bot.getUpdates()
# bot.sendMessage(chat_id=tlgm_id, text='시작' + str(balance))

asyncio.run(main(ticker))