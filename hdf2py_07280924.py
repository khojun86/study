import sys
import os
import re
import pandas as pd

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
    [범용 파서 함수]
    텍스트 표(ASCII Table) 형태의 로그를 동적으로 헤더를 읽어 딕셔너리 리스트로 변환합니다.
    """
    records = []
    lines = parsed_text.split('\n')
    
    headers = []
    
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
            
        # 파이프라인 기준으로 분리하고 양 끝 공백 제거
        cols = [col.strip() for col in line.split('|')[1:-1]]
        
        # 1. 동적 헤더 탐지: 표의 컬럼명 규격에 맞게 키워드 감지 (예: Slot, Frame 등 공통 필드 활용)
        if "Slot" in cols and ("Numerology" in cols or "Frame" in cols):
            headers = cols
            continue
            
        # 2. 데이터 행 파싱: 헤더가 정의된 상태에서 데이터 행('| 숫자 |')을 만나면 동적 맵핑
        if re.match(r'^\|\s*\d+\|', line) and headers:
            if len(cols) == len(headers):
                # 딕셔너리로 기본 맵핑 생성
                record = dict(zip(headers, cols))
                # 메타데이터 추가
                record["Timestamp"] = timestamp
                record["Packet_Name"] = packet_name
                records.append(record)
            else:
                # 컬럼 개수가 일치하지 않는 예외 행 처리 (필요시 보완)
                pass
                
    return records


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
            
            print("\n" + "="*80)
            print(f"성공! 로그 코드 [{target_log_code}] 데이터 프레임 변환 완료 (총 {len(df)}행)")
            print(df.head(10).to_string())
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