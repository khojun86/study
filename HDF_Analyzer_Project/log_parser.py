import sys
import re
import pandas as pd

# QUTS Python API 경로 환경 변수 추가
quts_api_path = r"C:\Program Files\Qualcomm\QUTS\Support\python"
if quts_api_path not in sys.path:
    sys.path.append(quts_api_path)

try:
    import Common.ttypes
    import LogSession.ttypes
except ImportError as e:
    print(f"QUTS 모듈 임포트 실패 (log_parser): {e}")

def parse_ascii_table(timestamp, packet_name, parsed_text):
    """0xB887(DL), 0xB883(UL Sch), 0xB884(UL Pwr) 공통 ASCII 테이블 파서"""
    records = []
    lines = parsed_text.split('\n') 
    sep_indices = [i for i, line in enumerate(lines) if line.strip() and set(line.strip()) == {'-'}]
    
    if len(sep_indices) >= 2:
        header_lines = lines[sep_indices[0] + 1 : sep_indices[1]]
        reference_line = header_lines[-1]
        
        pipe_indices = [i for i, char in enumerate(reference_line) if char == '|']
        num_cols = len(pipe_indices) - 1
        merged_headers = ["" for _ in range(num_cols)]
        
        for h_line in header_lines:
            h_line = h_line.ljust(len(reference_line))
            for j in range(num_cols):
                start_idx = pipe_indices[j] + 1
                end_idx = pipe_indices[j + 1]
                
                # [핵심 수정] 병합된 셀의 텍스트가 엉뚱하게 섞이지 않도록, 
                # 현재 줄의 경계에 정확히 파이프(|) 기호가 닫혀 있을 때만 텍스트를 추출합니다.
                if h_line[start_idx - 1] == '|' and h_line[end_idx] == '|':
                    text = h_line[start_idx:end_idx].strip()
                    if text:
                        merged_headers[j] = (merged_headers[j] + " " + text).strip() if merged_headers[j] else text
                        
        for i in range(sep_indices[1] + 1, len(lines)):
            line = lines[i]
            if not line.strip() or set(line.strip()) == {'-'}: 
                continue 
            line = line.ljust(len(reference_line))
            cols = [line[pipe_indices[j]+1 : pipe_indices[j+1]].strip() for j in range(num_cols)]
            
            if len(cols) == num_cols:
                record = dict(zip(merged_headers, cols))
                record["Timestamp"] = timestamp 
                record["Packet_Name"] = packet_name
                records.append(record)
    return records


def parse_b8d8(timestamp, packet_name, parsed_text):
    # (기존 코드와 동일)
    if "Reference Signal = SSB" not in parsed_text:
        return []
    record = {"Timestamp": timestamp, "Packet_Name": packet_name}
    for i in range(4):
        match = re.search(rf'RX\[{i}\]\s*SNR =\s*([-\d\.]+)', parsed_text)
        if match:
            record[f'RX[{i}]_SNR'] = float(match.group(1))
    return [record] if len(record) > 2 else []


def parse_b97f(timestamp, packet_name, parsed_text):
    # (기존 코드와 동일)
    record = {"Timestamp": timestamp, "Packet_Name": packet_name}
    for i in range(4):
        match = re.search(rf'Serving RX\[{i}\]\s*RSRP =\s*([-\d\.]+)', parsed_text)
        if match:
            record[f'RX[{i}]_RSRP'] = float(match.group(1))
    match = re.search(r'\|\s*0\|\s*\d+\|\s*\d+\|\s*\d+\|\s*([-\d\.]+)', parsed_text)
    if match:
        record['Cell_Quality_RSRP'] = float(match.group(1))
    return [record] if len(record) > 2 else []


def extract_logs_to_dataframe(client, log_session, diag_protocol_handle, target_log_code):
    """특정 로그 코드를 추출하여 DataFrame으로 반환 (파서 자동 분기)"""
    all_parsed_data = []

    diag_packet_filter = Common.ttypes.DiagPacketFilter()
    diag_packet_filter.idOrNameMask = {
        Common.ttypes.DiagPacketType.LOG_PACKET: [Common.ttypes.DiagIdFilterItem(idOrName=target_log_code)]
    }
    
    data_packet_filter = LogSession.ttypes.DataPacketFilter()
    data_packet_filter.protocolHandleList = [diag_protocol_handle]
    data_packet_filter.diagFilter = diag_packet_filter

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
    
    print(f"[{target_log_code}] 데이터 추출 중...")
    data_packets = log_session.getDataViewItems(view_name, packet_range)
    
    for packet_wrapper in data_packets:
        if packet_wrapper.diagPacket and packet_wrapper.diagPacket.parsedText:
            packet = packet_wrapper.diagPacket
            ts, pname, text = packet.timeStampString, packet.packetName, packet.parsedText
            
            # [수정됨] B883, B884, B887 모두 공통 파서 사용
            if any(code in target_log_code for code in ["B887", "B883", "B884"]):
                all_parsed_data.extend(parse_ascii_table(ts, pname, text))
            elif "B8D8" in target_log_code:
                all_parsed_data.extend(parse_b8d8(ts, pname, text))
            elif "B97F" in target_log_code:
                all_parsed_data.extend(parse_b97f(ts, pname, text))

    log_session.removeDataView(view_name)
    
    if all_parsed_data:
        df = pd.DataFrame(all_parsed_data)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        return df.sort_values('Timestamp').reset_index(drop=True)
    return None