from pyupbit import WebSocketManager, pd
import pyupbit
import time
import sys
import numpy
import websockets
import asyncio
import json
import numpy as np
import pprint


# if __name__ == "__main__":
#    wm = WebSocketManager("ticker", ["KRW-ETC"])
#    for i in range(10):
#        data = wm.get()
#        print(data)
#    wm.terminate()

def sectionRising(data1, data2, data3):  # old state 를 만들어야댐

    if data1 < data2 < data3:
        return "up"
    elif data2 < data3:  # old state 를 참조해야댐
        return "reverse"
    else:
        return "down"


def iscrossed(old, new, benchmark):
    if old <= benchmark < new:
        return 'golden'
    elif old >= benchmark > new:
        return 'dead'
    else:
        return False


async def upbit_ws_client(ticker):
    url = "wss://api.upbit.com/websocket/v1"
    prevTime = ''
    tickprice = np.array([])
    tickgroup = 30
    firstbuyprice = 5010
    buyprice = firstbuyprice;sellprice = 0
    boughtedbalance = 0;boughtedvolume = 0;boughtedprice = 0
    grouptickclose = np.array([])
    state = 'none'
    bbl_last = 0; bbl=0
    margin=2.5
    # 초기 설정
    close = pyupbit.get_ohlcv(ticker, 'minute1', 1)
    close = close['close']
    if close[0] > 2000000:
        tic = 1000
    elif close[0] > 1000000:
        tic = 500
    elif close[0] > 500000:
        tic = 100
    elif close[0] > 100000:
        tic = 50
    elif close[0] > 10000:
        tic = 10
    elif close[0] > 1000:
        tic = 5
    elif close[0] > 100:
        tic = 1
    elif close[0] > 10:
        tic = 0.1
    else:
        tic = 0.01

    async with websockets.connect(url) as websocket:
        subscribe_fmt = [
            {"ticket": "test00"},
            {
                "type": "trade",
                "codes": [ticker],
                "isOnlyRealtime": True
            }
            # ,{"format":"SIMPLE"}
        ]
        subscribe_data = json.dumps(subscribe_fmt)
        await websocket.send(subscribe_data)
        while True:
            try:
                data = await websocket.recv()
            except Exception as e:
                print('힝')
            data = json.loads(data)
            # print(data)
            ##### 30 tic close : tickprice[tickgroup-1] ####
            if len(tickprice) < tickgroup:
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
            if nowTime != prevTime:
                df = pyupbit.get_ohlcv(ticker, 'minute1')
                df_close = df['close']
                df_volume = df['volume']

                #### minute candle moving average ####
                # minute_ma5 = df_close.rolling(5).mean()
                # minute_ma10 = df_close.rolling(10).mean()
                roll_ma20 = df_close.rolling(20)
                minute_ma20 = roll_ma20.mean()
                # minute_ma60 = df_close.rolling(60).mean()
                # minute_ma100 = df_close.rolling(100).mean()

                balance = upbit.get_balance("KRW")
                # print(nowTime,minute_ma5[199],minute_ma10[199],minute_ma20[199],minute_ma60[199],minute_ma100[199])
                # print(sectionRising(minute_ma5[189],minute_ma5[194],minute_ma5[199]))
                # rising_ma5 = sectionRising(minute_ma5[189],minute_ma5[194],minute_ma5[199])
                # rising_ma10 = sectionRising(minute_ma10[189], minute_ma10[194], minute_ma10[199])
                # rising_ma20 = sectionRising(minute_ma20[189], minute_ma20[194], minute_ma20[199])
                # rising_ma60 = sectionRising(minute_ma60[189], minute_ma60[194], minute_ma60[199])
                # rising_ma100 = sectionRising(minute_ma100[189], minute_ma100[194], minute_ma100[199])
                # print(rising_ma5,rising_ma10,rising_ma20,rising_ma60,rising_ma100)

                #### bollinger band coefficient = 2.4 ####
                bbl_last = bbl

                bbm = minute_ma20[199]
                bbl = bbm - roll_ma20.std()[199] * 2.4
                # bbu = bbm + roll_ma20.std()[199] * 2.4

                # print(round(bbl, 0), round(bbm, 0))
                print("BB 하단",round(bbl, 0))

            #### 현재가가 BB low 아래에 있을 때 매수가 결정 ####
            if data["trade_price"] < bbl and state == 'none' and balance >= buyprice:
                state = 'ready'
                if balance != init_balance:
                    if abp > data["trade_price"]:
                        buyprice = int(buyprice*1.1)
                    else:
                        buyprice = firstbuyprice
                if sellprice != 0:
                    selluuid = sellorder['uuid']
                    print('sell order =',selluuid)
                print(state,buyprice)
            #### 30tick close 의 ma 10 가 ma 60 을 돌파할 때 매수####
            if state == 'ready':
                tick30_ma60 = grouptickclose[5:65].mean()
                tick30_ma10last = grouptickclose[54:64].mean()
                tick30_ma10 = grouptickclose[55:65].mean()#;print(state)
                if tick30_ma10last <= tick30_ma60 < tick30_ma10 and np.isnan(tick30_ma60) == False:
                    print('매수지점', data["trade_price"])
                    if buyprice==firstbuyprice:
                        buy=upbit.buy_market_order(ticker, buyprice)
                        uuid=buy['uuid']
                        print(uuid,type(uuid))
                        state = 'buy';print(state)
                        # buyprice += 1
            #### 매수 한 다음 1분 중 매도가 결정 매도주문 ####
            if state == 'buy' and nowTime != prevTime:
                state = 'none';print(state)
                boughtedbalance += buyprice
                boughtedvolume = upbit.get_balance(ticker)-init_volume
                abp = boughtedbalance/boughtedvolume
                print('누적 Balance =',boughtedbalance,'누적 Volume =',boughtedvolume,'ABP =',round(abp,2),'\n','매도주문')
                if sellprice == 0:
                    sellprice = int(abp*(1+margin/100)/tic)*tic
                else:
                    print(upbit.cancel_order(selluuid))
                    sellprice = int(abp*(1+margin/100)/tic)*tic
                time.sleep(1)
                sellorder = upbit.sell_limit_order(ticker, sellprice, boughtedvolume)
                # selluuid = sellorder['uuid']
                pprint.pprint(sellorder)


            if nowTime != prevTime:
                prevTime = nowTime

async def main(ticker):
    await upbit_ws_client(ticker)


ticker = "KRW-ETC"
access_key = "GFexnbUxVxmu1ClL5oNaedEdGYwX4ZSzdcwn0806"
secret_key = "TS2cSWkl0vUkwGgmxQmyCdgeLydxNBlYacbowHp5"

upbit = pyupbit.Upbit(access_key, secret_key)
init_balance = upbit.get_balance("KRW")
init_volume = upbit.get_balance(ticker)
print("init_balance =",init_balance,"\ninit_volume =",init_volume, type(init_volume))
asyncio.run(main(ticker))
