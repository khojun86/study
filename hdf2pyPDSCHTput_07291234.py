import sys
import os
import re
import pandas as pd
import matplotlib.pyplot as plt

# 1. QUTS Python API 경로 환경 변수 추가
quts_api_path = r"C:\Program Files\Qualcomm\QUTS\Support\python"
if quts_api_path not in sys.path:
    sys.path.append(quts_api_path)

try:
    import QutsClient
    import Common.ttypes
    import LogSession.ttypes
except ImportError as e:
    print(f"QUTS 모듈 임포트 실패: {e}")
    sys.exit(1)


def parse_generic_ascii_table(timestamp, packet_name, parsed_text):
    """
    [공용 파서 함수] 
    절대 좌표(인덱스) Slicing 방식을 사용하여 3~4줄에 걸쳐 병합된 다중 행 헤더와 
    데이터를 손실 없이 완벽하게 맵핑하여 딕셔너리 리스트로 반환합니다.
    """
    records = []
    lines = parsed_text.split('\n') 
    
    # 구분선(---) 인덱스 찾기
    sep_indices = [i for i, line in enumerate(lines) if line.strip() and set(line.strip()) == {'-'}]
    
    if len(sep_indices) >= 2:
        header_lines = lines[sep_indices[0] + 1 : sep_indices[1]]
        reference_line = header_lines[-1]
        
        # 마지막 헤더 줄의 파이프(|) 위치 좌표 추출
        pipe_indices = [i for i, char in enumerate(reference_line) if char == '|']
        num_cols = len(pipe_indices) - 1
        
        merged_headers = ["" for _ in range(num_cols)]
        
        # 절대 좌표 기반 세로 칸 병합 (상위 병합 헤더의 누락 방지)
        for h_line in header_lines:
            h_line = h_line.ljust(len(reference_line))
            for j in range(num_cols):
                start_idx = pipe_indices[j] + 1
                end_idx = pipe_indices[j + 1]
                text = h_line[start_idx:end_idx].strip()
                if text:
                    if merged_headers[j]:
                        merged_headers[j] += " " + text
                    else:
                        merged_headers[j] = text
                        
        # 데이터 파싱 (동일한 좌표 Slicing 적용)
        for i in range(sep_indices[1] + 1, len(lines)):
            line = lines[i]
            if not line.strip() or set(line.strip()) == {'-'}: 
                continue 
            
            line = line.ljust(len(reference_line))
            cols = []
            for j in range(num_cols):
                start_idx = pipe_indices[j] + 1
                end_idx = pipe_indices[j + 1]
                cols.append(line[start_idx:end_idx].strip())
            
            if len(cols) == num_cols:
                record = dict(zip(merged_headers, cols))
                record["Timestamp"] = timestamp 
                record["Packet_Name"] = packet_name  # 요청하신 Packet_Name 추가!
                records.append(record)
                
    return records


def calculate_and_plot_throughput_advanced(df):
    """
    100ms 윈도우와 1초 윈도우 기반의 Throughput을 동시에 계산하고
    수치 라벨링과 함께 겹쳐서 보여줍니다.
    """
    print("다중 윈도우(100ms & 1s) Throughput 산출을 시작합니다...")

    # CRC State 필터링 (컬럼명이 'CRC State' 또는 'State'로 잡힐 수 있으므로 유연하게 대응)
    crc_col = 'CRC State' ## if 'CRC State' in df.columns else 'State'
    
    if crc_col in df.columns:
        original_len = len(df)
        df = df[df[crc_col].astype(str).str.contains('Pass', case=False, na=False)].copy()
        print(f"CRC 필터링 완료: 전체 {original_len}개 중 유효(Pass) 패킷 {len(df)}개 추출")
    else:
        print(f"[경고] CRC 상태 컬럼을 찾지 못했습니다. 현재 컬럼: {df.columns.tolist()}")
    # 1. 데이터 전처리
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    df['TB Size'] = pd.to_numeric(df['TB Size'], errors='coerce').fillna(0)
    df_time_indexed = df.set_index('Timestamp')
    
    # 2. 100ms Window 계산 (0.1초 기준)
    df_100ms = df_time_indexed.resample('100ms').agg({'TB Size': 'sum'}).fillna(0)
    df_100ms['Throughput_Mbps'] = (df_100ms['TB Size'] * 8) / 0.1 / 1_000_000
    
    # 3. 1초(1s) Window 계산 (1.0초 기준)
    # '1S'는 Pandas에서 1초 단위 리샘플링을 의미합니다.
    df_1s = df_time_indexed.resample('1s').agg({'TB Size': 'sum'}).fillna(0)
    df_1s['Throughput_Mbps'] = (df_1s['TB Size'] * 8) / 1.0 / 1_000_000
    
    # 4. Matplotlib 시각화 (그래프 겹치기)
    fig, ax = plt.subplots(figsize=(15, 7))
    
    # [백그라운드] 100ms 그래프: 변동성을 보기 위해 얇고 반투명하게 설정
    ax.plot(
        df_100ms.index, 
        df_100ms['Throughput_Mbps'], 
        color='#1f77b4', # 파란색
        alpha=0.4,       # 투명도 40%
        linewidth=1.0, 
        label='100ms Window'
    )
    
    # [포그라운드] 1초 그래프: 트렌드를 보기 위해 두껍고 마커를 추가
    ax.plot(
        df_1s.index, 
        df_1s['Throughput_Mbps'], 
        color='#ff7f0e', # 주황색
        marker='o',      # 데이터 포인트에 동그라미 마커
        linewidth=2.5, 
        label='1 Sec Window (Average)'
    )
    
    # [수치 표기] 1초 단위 Throughput 값을 그래프 위에 텍스트로 출력
    for idx, row in df_1s.iterrows():
        val = row['Throughput_Mbps']
        # 데이터가 너무 많아 겹치는 것을 방지하기 위해 0 Mbps 이상일 때만 표기 (필요시 조건 조정 가능)
        if val >= 0: 
            ax.text(
                idx, 
                val + (val * 0.05), # 마커보다 살짝 위쪽에 텍스트 위치
                f'{val:.1f}',       # 소수점 1자리까지 표기
                color='#d62728',    # 빨간색 텍스트
                fontsize=9, 
                ha='center',        # 가운데 정렬
                va='bottom',
                fontweight='bold'
            )
    
    # 5. 그래프 꾸미기
    ax.set_title('PDSCH MAC Throughput (100ms vs 1sec)', fontsize=16, fontweight='bold')
    ax.set_xlabel('System Time', fontsize=12)
    ax.set_ylabel('Throughput (Mbps)', fontsize=12)
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.legend(loc='upper right', fontsize=11)
    
    # X축 시간 포맷이 겹치지 않게 회전
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # 그래프 출력
    plt.show()
    
    return df_100ms, df_1s

def extract_logs_to_dataframe(hdf_file_path, target_log_code):
    """
    원하는 로그 코드(예: '0xB887' 등)를 입력받아 HDF 파일에서 추출하고 DataFrame으로 반환합니다.
    """
    client = QutsClient.QutsClient("L1L2_Generic_Parser")
    log_session = None
    all_parsed_data = []

    try:
        print(f"HDF 파일 로드 중: {hdf_file_path} ...")
        log_session = client.openLogSession([hdf_file_path])
        
        device_list = log_session.getDeviceList()
        if not device_list:
            print("로그 파일에서 디바이스 정보를 찾을 수 없습니다.")
            return
        
        list_of_protocols = log_session.getProtocolList(device_list[0].deviceHandle)
        diag_protocol_handle = next((p.protocolHandle for p in list_of_protocols if p.protocolType == Common.ttypes.ProtocolType.PROT_DIAG), None)
        
        if not diag_protocol_handle:
            print("DIAG 프로토콜 핸들을 찾을 수 없습니다.")
            return

        # 동적 로그 코드 필터링 적용
        diag_packet_filter = Common.ttypes.DiagPacketFilter()
        diag_packet_filter.idOrNameMask = {
            Common.ttypes.DiagPacketType.LOG_PACKET: [Common.ttypes.DiagIdFilterItem(idOrName=target_log_code)]
        }
        
        data_packet_filter = LogSession.ttypes.DataPacketFilter()
        data_packet_filter.protocolHandleList = [diag_protocol_handle]
        data_packet_filter.diagFilter = diag_packet_filter

        # 필수 플래그 설정 (PARSED_TEXT 및 PACKET_NAME 포함)
        return_obj_diag = Common.ttypes.DiagReturnConfig()
        return_obj_diag.flags = (Common.ttypes.DiagReturnFlags.PARSED_TEXT |
                                 Common.ttypes.DiagReturnFlags.PACKET_NAME |
                                 Common.ttypes.DiagReturnFlags.PACKET_ID |
                                 Common.ttypes.DiagReturnFlags.TIME_STAMP_STRING)
                                 
        packet_return_config = LogSession.ttypes.PacketReturnConfig()
        packet_return_config.diagConfig = return_obj_diag
        
        view_name = f"View_{target_log_code}"
        log_session.createDataView(view_name, data_packet_filter, packet_return_config)
        
        packet_range = LogSession.ttypes.PacketRange()
        packet_range.beginIndex = 0
        packet_range.endIndex = log_session.getDataPacketCount(diag_protocol_handle)
        
        print(f"로그 코드 [{target_log_code}] 패킷 추출 및 파싱 시작...")
        data_packets = log_session.getDataViewItems(view_name, packet_range)
        
        for packet_wrapper in data_packets:
            if packet_wrapper.diagPacket and packet_wrapper.diagPacket.parsedText:
                packet = packet_wrapper.diagPacket
                # 범용 파서 호출 (패킷 이름도 함께 전달)
                parsed_records = parse_generic_ascii_table(
                    timestamp=packet.timeStampString, 
                    packet_name=packet.packetName, 
                    parsed_text=packet.parsedText
                )
                all_parsed_data.extend(parsed_records)

        # Pandas DataFrame 변환
        if all_parsed_data:
            df = pd.DataFrame(all_parsed_data)
            final_100ms_df, final_1s_df = calculate_and_plot_throughput_advanced(df)
            
            print("\n" + "="*80)
            print(f"성공! 로그 코드 [{target_log_code}] 데이터 프레임 변환 완료 (총 {len(df)}행)")
            print(df.head(10).to_string())
            print(final_1s_df.to_string())
            print("="*80)
            
            # 필요시 CSV로 즉시 내보내기 가능
            # output_csv = f"C:\\Users\\Home\\Desktop\\dad\\hdf2py\\Log_{target_log_code}.csv"
            # df.to_csv(output_csv, index=False)
            # print(f"파일 저장 완료: {output_csv}")
        else:
            print(f"로그 코드 [{target_log_code}]에 해당하는 파싱 가능한 데이터가 없습니다.")

    except Exception as e:
        print(f"처리 중 에러 발생: {e}")
    finally:
        if log_session:
            try: log_session.removeDataView(f"View_{target_log_code}")
            except: pass
            log_session.destroyLogSession()
        print("작업이 완료되었습니다.")

if __name__ == "__main__":
    test_hdf_file = r"C:\Users\Home\Desktop\dad\hdf2py\test.hdf"
    
    if os.path.exists(test_hdf_file):
        # 함수형태로 빼두었기 때문에, 원하시는 다른 로그 코드로 언제든 변경해서 호출 가능합니다!
        extract_logs_to_dataframe(test_hdf_file, target_log_code="0xB887")
    else:
        print(f"파일을 찾을 수 없습니다: {test_hdf_file}")