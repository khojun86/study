from pyupbit import WebSocketManager, pd
import pyupbit
import time
import websockets
import telegram
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

# def sectionRising(data1, data2, data3):  # old state 를 만들어야댐
#
#     if data1 < data2 < data3:
#         return "up"
#     elif data2 < data3:  # old state 를 참조해야댐
#         return "reverse"
#     else:
#         return "down"
#
#
# def iscrossed(old, new, benchmark):
#     if old <= benchmark < new:
#         return 'golden'
#     elif old >= benchmark > new:
#         return 'dead'
#     else:
#         return False


async def upbit_ws_client(ticker):
    url = "wss://api.upbit.com/websocket/v1"
    prevTime = '';buyTime = time.strftime('%H:%M')
    tickprice = np.array([])
    # tickgroup = 30
    firstbuyprice = 5010
    buyprice = firstbuyprice;sellprice = 0
    boughtedbalance = 0;boughtedvolume = 0;boughtedprice = 0
    grouptickclose = np.array([])
    state = 'none';selluuid=''
    # 초기 설정
    init_balance = upbit.get_balance("KRW")
    init_volume = upbit.get_balance(ticker)
    #### telegram alarm ####
    # print("init_balance =", init_balance, "\ninit_volume =", init_volume)
    ####  ohlcv 변동 폭 계산 ####
    df = pyupbit.get_ohlcv(ticker, interval="minute240", count=10)
    lastlow = np.array(df['low'].tolist())
    nexthigh = np.array(df['high'].tolist())
    # print(nexthigh[1:len(nexthigh)]);print(lastlow[0:len(nexthigh)-1])
    nexthigh = nexthigh[1:len(nexthigh)]
    lastlow = lastlow[0:len(lastlow) - 1]
    # print((nexthigh-lastlow)/lastlow*100)
    range = (nexthigh - lastlow) / lastlow * 100
    df = pyupbit.get_ohlcv(ticker,count=1)
    # pprint.pprint(df)
    # print(df['high'],df['low'],(df['high']-df['low'])/df['low'])
    dayrange=np.array((df['high']-df['low'])/df['low'])
    margin = float(np.mean(range) / 2.8)+dayrange[-1] / 1.5
    ## tic 판단
    close = nexthigh[-1]
    if close > 2000000: tic = 1000
    elif close > 1000000: tic = 500
    elif close > 500000: tic = 100
    elif close > 100000: tic = 50
    elif close > 10000: tic = 10
    elif close > 1000: tic = 5
    elif close > 100: tic = 1
    elif close > 10: tic = 0.1
    else: tic = 0.01
    print('margin =', margin)
    bbl_last = 0; bbl=0

    ## 초기 주문 있을 때 대응
    init_order=upbit.get_order(ticker)
    if len(init_order)!=0:
        # print(init_order[0])
        remains=upbit.get_balances()[1]
        ordered_abp=remains['avg_buy_price']
        ordered_volume=remains['locked']
        ordered_totalbalance=float(ordered_abp)*float(ordered_volume)
        # print(ordered_abp,ordered_volume,ordered_totalbalance)
        upbit.cancel_order(init_order[0]['uuid'])
        time.sleep(1)
        boughtedbalance = ordered_totalbalance
        boughtedvolume = ordered_volume


    async with websockets.connect(url) as websocket:
        subscribe_fmt = [{"ticket": "test00"},{"type": "trade","codes": [ticker],"isOnlyRealtime": True}]
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
                if nowTime != prevTime:
                    df = pyupbit.get_ohlcv(ticker, 'minute1')
                    df_close = df['close']
                    # df_volume = df['volume']

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
                    bbu = bbm + roll_ma20.std()[199] * 2.4 # print(round(bbl, 0), round(bbm, 0));print("BB 하단",round(bbl, 0))
                    #### 0817 update 매도 가 이상 도달 시
                    if sellprice !=0 and data["trade_price"]>sellprice:
                        boughtedbalance = 0;boughtedvolume = 0;sellprice = 0;selluuid = ''
                        init_balance = balance;init_volume = upbit.get_balance(ticker)
                        print("매도확인 =\033[31m",init_balance, "\033[0m")
                        #### telegram alarm ####
                        bot.sendMessage(chat_id=tlgm_id, text='현재' + str(init_balance))

                    prevTime = nowTime

                #### 현재가가 BB low 아래에 있을 때 매수 결정 ####
                if data["trade_price"] < bbl and state == 'none' and balance >= buyprice and len(grouptickclose) == 65 and nowTime!=buyTime:
                    state = 'ready'
                    if balance != init_balance:
                        if abp > data["trade_price"]:
                            buyprice = int(buyprice*1.1)
                        else:
                            buyprice = firstbuyprice
                    if sellprice != 0:
                        selluuid = sellorder['uuid']
                        print('sell order =',selluuid)
                    print(time.strftime('%H:%M'),buyprice,"원 준비")
                #### 30tick close 의 ma 10 가 ma 30 을 돌파할 때 매수####  ## 0817 update
                if state == 'ready':
                    tick30_ma50 = grouptickclose[15:65].mean()
                    tick30_ma10last = grouptickclose[54:64].mean()
                    tick30_ma10 = grouptickclose[55:65].mean()#;print(state)
                    if tick30_ma10last <= tick30_ma50 < tick30_ma10 and np.isnan(tick30_ma50) == False:
                        print(time.strftime('%H:%M'),'매수시간')
                        buy=upbit.buy_market_order(ticker, buyprice)
                        uuid=buy['uuid']
                        # print(uuid,type(uuid))
                        state = 'buy';print(state)
                        # buyprice += 1
                        buyTime = time.strftime('%H:%M')
                #### 매수 한 다음 1분 중 매도가 결정 매도주문 ####
                if state == 'buy' and nowTime != prevTime:
                    state = 'none'
                    # print(state)
                    boughtedbalance += upbit.get_order(ticker)
                    boughtedvolume += upbit.get_balance(ticker)-init_volume
                    abp = boughtedbalance/boughtedvolume
                    print('Bought Balance =',boughtedbalance,'Bought Volume =',round(boughtedvolume,2),'ABP =',round(abp,2))
                    # print('ABP+1%',round(abp*1.01,2),'ABP+2%',round(abp*1.02,2),'ABP+3%',round(abp*1.03,2))
                          # ,'\n','매도주문')
                    if sellprice == 0:
                        sellprice = int(abp*(1+margin/100)/tic)*tic
                    else:
                        upbit.cancel_order(selluuid)
                        time.sleep(2)
                        sellprice = int(abp*(1+margin/100)/tic)*tic
                        # pprint.pprint(upbit.get_order(ticker))
                        time.sleep(2)
                    print(time.strftime('%H:%M'),"매도가 ABP+",margin,"% = ",sellprice)
                    sellorder = upbit.sell_limit_order(ticker, sellprice, boughtedvolume)
                    time.sleep(2)
                    selluuid = sellorder['uuid']
                    # pprint.pprint(sellorder)

                # if nowTime != prevTime:
                #     #### 0526 update 매도 주문 체결 시 초기화 ####
                #     # order = upbit.get_order(ticker, state="wait")
                #     # sellstate = 0
                #     # if len(order) != 0:
                #     #     for i in order:
                #     #         if i['uuid'] == selluuid:
                #     #             sellstate += 1
                #     #         else:
                #     #             sellstate += 0
                #     #     if sellstate == 0 and selluuid != '':
                #     #         boughtedbalance = 0;boughtedvolume = 0;sellprice = 0;selluuid=''
                #     #         init_balance = upbit.get_balance("KRW")
                #     #         init_volume = upbit.get_balance(ticker)
                #     #         print("매도체결\n","init_balance =", init_balance, "\ninit_volume =", init_volume)
                #
                #     #### 0817 update 매도 주문 힝 발생 시
                #     # 연구필요
                #
                #     #### 0817 update 매도 가 이상 도달 시
                #     if sellprice !=0 and data["trade_price"]>sellprice:
                #         print("헹")
                #     prevTime = nowTime
            except Exception as e:
                print('힝')
async def main(ticker):
    await upbit_ws_client(ticker)


ticker = "KRW-ETC"
access_key = "GFexnbUxVxmu1ClL5oNaedEdGYwX4ZSzdcwn0806"
secret_key = "TS2cSWkl0vUkwGgmxQmyCdgeLydxNBlYacbowHp5"

upbit = pyupbit.Upbit(access_key, secret_key)
# print("init_balance =",upbit.get_balance("KRW"),"\ninit_volume =",upbit.get_balance(ticker))
balance=upbit.get_balance("KRW")
print("init_balance =\033[31m",balance,"\033[0m")
# pprint.pprint(upbit.get_order(ticker))

# 텔레그램 연결
tlgm_token = '1733326409:AAFVLFVWG2nPJcP65YcglWgQKeKLQtJuzE4'
tlgm_id = '1758620562'
bot = telegram.Bot(token = tlgm_token)
updates = bot.getUpdates()
bot.sendMessage(chat_id=tlgm_id, text='시작'+str(balance))
# telegram_mid=bot.getUpdates()[-1].message.message_id


asyncio.run(main(ticker))
