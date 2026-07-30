import sys
import os
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# QUTS Python API 경로 환경 변수 추가
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


# ==========================================
# 1. 파싱 함수 모음 (0xB887, 0xB8D8, 0xB97F)
# ==========================================
def parse_b887(timestamp, packet_name, parsed_text):
    """기존 0xB887 파서 (ASCII 테이블)"""
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
    """0xB8D8 파서 (SSB SNR 추출)"""
    if "Reference Signal = SSB" not in parsed_text:
        return []
    
    record = {"Timestamp": timestamp, "Packet_Name": packet_name}
    for i in range(4):
        # 정규식을 통해 "RX[0] \n SNR = 27.54 dB" 패턴에서 숫자만 추출
        match = re.search(rf'RX\[{i}\]\s*SNR =\s*([-\d\.]+)', parsed_text)
        if match:
            record[f'RX[{i}]_SNR'] = float(match.group(1))
            
    # 최소한 RX[0] 데이터라도 있으면 유효한 패킷으로 간주
    return [record] if len(record) > 2 else []


def parse_b97f(timestamp, packet_name, parsed_text):
    """0xB97F 파서 (Serving RSRP 및 Cell Quality 추출)"""
    record = {"Timestamp": timestamp, "Packet_Name": packet_name}
    
    # 1. Serving RX RSRP 추출
    for i in range(4):
        match = re.search(rf'Serving RX\[{i}\]\s*RSRP =\s*([-\d\.]+)', parsed_text)
        if match:
            record[f'RX[{i}]_RSRP'] = float(match.group(1))
            
    # 2. Cell Quality RSRP 추출 (테이블에서 0번 인덱스 행 검색)
    # 패턴: |  0|   210|    84|    1|      -82.51|
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
            
            # 로그 코드에 따라 알맞은 파서 호출
            if "B887" in target_log_code:
                all_parsed_data.extend(parse_b887(ts, pname, text))
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

import numpy as np
import matplotlib.gridspec as gridspec

# ==========================================
# 2. 데이터 병합 (pd.cut) 및 다중 지표 시각화 엔진
# ==========================================
def calculate_and_plot_time_series(df_b887, file_window_dict):
    """시간축 기반 Throughput, BLER, MCS, Layer, RB 다중 그래프 렌더링"""
    # 3행 2열의 격자(Grid) 생성 (첫 줄은 Throughput이 넓게 차지)
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(3, 2, figure=fig)
    
    ax_thr = fig.add_subplot(gs[0, :])   # Throughput (전체 너비)
    ax_bler = fig.add_subplot(gs[1, 0])  # BLER
    ax_mcs = fig.add_subplot(gs[1, 1])   # MCS
    ax_layer = fig.add_subplot(gs[2, 0]) # Layer
    ax_rb = fig.add_subplot(gs[2, 1])    # RB
    
    all_windowed_dfs = []
    if 'Source_File' not in df_b887.columns:
        df_b887['Source_File'] = 'Single_File'
        
    crc_col = 'CRC State' if 'CRC State' in df_b887.columns else 'State'
    
    for file_name, df_group in df_b887.groupby('Source_File'):
        df_group = df_group.copy()
        window_size = file_window_dict.get(file_name, '100ms')
        window_sec = pd.to_timedelta(window_size).total_seconds()
        
        # 숫자형 변환 및 결측치 처리
        for col in ['TB Size', 'MCS', 'Num Layers', 'Num Rbs']:
            if col in df_group.columns:
                df_group[col] = pd.to_numeric(df_group[col], errors='coerce').fillna(0)
            else:
                df_group[col] = 0
                
        # CRC Pass 여부를 Boolean으로 저장 (BLER 계산을 위해 전체 패킷 유지)
        df_group['is_pass'] = df_group[crc_col].astype(str).str.contains('Pass', case=False, na=False)
        df_group['Timestamp'] = pd.to_datetime(df_group['Timestamp'])
        df_time_indexed = df_group.set_index('Timestamp')
        
        # 1. Throughput 계산 (Pass된 패킷들의 TB Size 합)
        df_pass = df_time_indexed[df_time_indexed['is_pass']]
        df_thr = df_pass.resample(window_size).agg({'TB Size': 'sum'}).fillna(0)
        df_thr['Throughput_Mbps'] = (df_thr['TB Size'] * 8) / window_sec / 1_000_000
        
        # 2. 다중 지표 통계 계산 (전체 패킷 기준)
        df_metrics = df_time_indexed.resample(window_size).agg({
            'is_pass': ['count', 'sum'], # 총 패킷 수, Pass 패킷 수
            'MCS': 'mean',
            'Num Layers': 'mean',
            'Num Rbs': 'mean'
        }).fillna(0)
        
        # 멀티인덱스 평탄화 및 BLER 계산
        df_metrics.columns = ['Total_Pkts', 'Pass_Pkts', 'MCS_Mean', 'Layer_Mean', 'RB_Mean']
        df_metrics['BLER_Pct'] = np.where(df_metrics['Total_Pkts'] > 0, 
                                         (df_metrics['Total_Pkts'] - df_metrics['Pass_Pkts']) / df_metrics['Total_Pkts'] * 100, 0)
        
        # 플로팅(Plotting)
        label_name = f'{file_name} ({window_size})'
        ax_thr.plot(df_thr.index, df_thr['Throughput_Mbps'], linewidth=2.0, label=label_name)
        ax_bler.plot(df_metrics.index, df_metrics['BLER_Pct'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_mcs.plot(df_metrics.index, df_metrics['MCS_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_layer.plot(df_metrics.index, df_metrics['Layer_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_rb.plot(df_metrics.index, df_metrics['RB_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        
        # CSV 저장을 위한 데이터 병합
        df_out = pd.concat([df_thr['Throughput_Mbps'], df_metrics], axis=1).reset_index()
        df_out['Source_File'] = file_name
        df_out['Window_Size'] = window_size
        all_windowed_dfs.append(df_out)
    
    # 각 서브플롯 꾸미기
    axes_config = [
        (ax_thr, 'PDSCH MAC Throughput', 'Throughput (Mbps)'),
        (ax_bler, 'Block Error Rate (BLER)', 'BLER (%)'),
        (ax_mcs, 'Average MCS', 'MCS Index'),
        (ax_layer, 'Average Number of Layers', 'Layers'),
        (ax_rb, 'Average Number of RBs', 'Resource Blocks')
    ]
    
    for ax, title, ylabel in axes_config:
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.7)
        if ax != ax_thr: ax.set_xlabel('System Time', fontsize=9)
    
    ax_thr.legend(loc='upper right', fontsize=9)
    plt.tight_layout()
    
    final_csv_df = pd.concat(all_windowed_dfs, ignore_index=True) if all_windowed_dfs else None
    return fig, final_csv_df


def calculate_and_plot_scatter(df_thr, df_ref, file_cols_dict, title, xlabel):
    """기준 로그 주기별 산점도(Throughput, BLER, MCS, Layer, RB) 다중 렌더링"""
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(3, 2, figure=fig)
    
    ax_thr = fig.add_subplot(gs[0, :])   
    ax_bler = fig.add_subplot(gs[1, 0])  
    ax_mcs = fig.add_subplot(gs[1, 1])   
    ax_layer = fig.add_subplot(gs[2, 0]) 
    ax_rb = fig.add_subplot(gs[2, 1])    
    
    if 'Source_File' not in df_thr.columns: df_thr['Source_File'] = 'Single_File'
    if 'Source_File' not in df_ref.columns: df_ref['Source_File'] = 'Single_File'

    crc_col = 'CRC State' if 'CRC State' in df_thr.columns else 'State'
    colors = plt.get_cmap('tab10').colors 
    color_idx = 0
    all_merged_dfs = []
    
    for file_name in df_ref['Source_File'].unique():
        x_cols = file_cols_dict.get(file_name, [])
        if not x_cols: continue
            
        df_thr_sub = df_thr[df_thr['Source_File'] == file_name].copy()
        df_ref_sub = df_ref[df_ref['Source_File'] == file_name].copy()
        if df_thr_sub.empty or df_ref_sub.empty: continue
            
        for col in ['TB Size', 'MCS', 'Num Layers', 'Num Rbs']:
            df_thr_sub[col] = pd.to_numeric(df_thr_sub.get(col, 0), errors='coerce').fillna(0)
            
        df_thr_sub['is_pass'] = df_thr_sub[crc_col].astype(str).str.contains('Pass', case=False, na=False)
        df_thr_sub['Timestamp'] = pd.to_datetime(df_thr_sub['Timestamp']).astype('datetime64[ns]')
        df_ref_sub['Timestamp'] = pd.to_datetime(df_ref_sub['Timestamp']).astype('datetime64[ns]')
        
        bins = df_ref_sub['Timestamp'].tolist()
        last_time = max(df_thr_sub['Timestamp'].max(), df_ref_sub['Timestamp'].max()) + pd.Timedelta(seconds=1)
        bins.append(last_time)
        
        df_thr_sub['time_bin'] = pd.cut(df_thr_sub['Timestamp'], bins=bins, right=False)
        
        # 각 구간별로 Pass된 TB Size와 다중 지표 통계를 동시에 계산
        grouped = df_thr_sub.groupby('time_bin', observed=False).agg(
            TB_Size_Pass=('TB Size', lambda x: x[df_thr_sub.loc[x.index, 'is_pass']].sum()),
            Total_Pkts=('is_pass', 'count'),
            Pass_Pkts=('is_pass', 'sum'),
            MCS_Mean=('MCS', 'mean'),
            Layer_Mean=('Num Layers', 'mean'),
            RB_Mean=('Num Rbs', 'mean')
        ).reset_index()
        
        grouped['ref_time'] = grouped['time_bin'].apply(lambda x: x.left if pd.notnull(x) else pd.NaT)
        grouped['ref_time'] = pd.to_datetime(grouped['ref_time']).astype('datetime64[ns]')
        grouped = grouped.drop(columns=['time_bin'])
        
        grouped['BLER_Pct'] = np.where(grouped['Total_Pkts'] > 0, 
                                      (grouped['Total_Pkts'] - grouped['Pass_Pkts']) / grouped['Total_Pkts'] * 100, 0)
        
        df_ref_sub['duration'] = df_ref_sub['Timestamp'].diff().shift(-1).dt.total_seconds().fillna(0.1) 
        df_ref_sub = df_ref_sub[df_ref_sub['duration'] > 0] 
        
        df_merged = pd.merge(df_ref_sub, grouped, left_on='Timestamp', right_on='ref_time', how='left').fillna(0)
        df_merged['Throughput_Mbps'] = (df_merged['TB_Size_Pass'] * 8) / df_merged['duration'] / 1_000_000
        df_merged['Source_File'] = file_name
        all_merged_dfs.append(df_merged)
        
        for col in x_cols:
            if col in df_merged.columns:
                valid_data = df_merged.dropna(subset=[col])
                if not valid_data.empty:
                    label = f'{file_name} - {col}'
                    c = colors[color_idx % len(colors)]
                    
                    ax_thr.scatter(valid_data[col], valid_data['Throughput_Mbps'], label=label, alpha=0.7, edgecolors='k', color=c)
                    ax_bler.scatter(valid_data[col], valid_data['BLER_Pct'], alpha=0.6, edgecolors='k', color=c)
                    ax_mcs.scatter(valid_data[col], valid_data['MCS_Mean'], alpha=0.6, edgecolors='k', color=c)
                    ax_layer.scatter(valid_data[col], valid_data['Layer_Mean'], alpha=0.6, edgecolors='k', color=c)
                    ax_rb.scatter(valid_data[col], valid_data['RB_Mean'], alpha=0.6, edgecolors='k', color=c)
                    color_idx += 1

    axes_config = [
        (ax_thr, f'{title} (Throughput)', 'Throughput (Mbps)'),
        (ax_bler, 'BLER', 'BLER (%)'),
        (ax_mcs, 'Average MCS', 'MCS Index'),
        (ax_layer, 'Average Layers', 'Layers'),
        (ax_rb, 'Average RBs', 'Resource Blocks')
    ]
    
    for ax, sub_title, ylabel in axes_config:
        ax.set_title(sub_title, fontsize=12, fontweight='bold')
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.7)
    
    if all_merged_dfs:
        ax_thr.legend(loc='upper right', fontsize=8, bbox_to_anchor=(1.0, 1.05))
    plt.tight_layout()
    
    final_csv_df = pd.concat(all_merged_dfs, ignore_index=True) if all_merged_dfs else None
    return fig, final_csv_df

# ==========================================
# 3. GUI 메인 클래스 (파일별 옵션 개별 제어 적용)
# ==========================================
class LogAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HDF Log Analyzer - Multi-File Individual Options")
        self.root.geometry("1200x950")        
        self.selected_files = [] 
        self.extracted_mode = "" 
        self.df_b887_cache = None
        self.df_ref_cache = None
        self.current_fig = None
        self.current_csv_df = None
        
        # --- Top Frame: 파일 선택 ---
        top_frame = tk.Frame(root, pady=10, padx=10)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="HDF Files: ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.file_path_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.file_path_var, width=80, state='readonly').pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text="Browse...", command=self.select_file).pack(side=tk.LEFT)

        # --- Middle Frame: 분석 모드 및 실행 ---
        mid_frame = tk.Frame(root, pady=10, padx=10)
        mid_frame.pack(fill=tk.X)
        tk.Label(mid_frame, text="Analysis Mode: ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="Time vs Throughput")
        self.mode_var.trace("w", self.update_options)
        
        modes = ["Time vs Throughput", "SNR vs Throughput (0xB8D8)", "RSRP vs Throughput (0xB97F)"]
        for mode in modes:
            tk.Radiobutton(mid_frame, text=mode, variable=self.mode_var, value=mode).pack(side=tk.LEFT, padx=5)
            
        tk.Button(mid_frame, text="Run Analysis", command=self.run_analysis, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side=tk.RIGHT, padx=20)

        # --- Option Frame: 동적 옵션 생성 영역 ---
        self.opt_frame = tk.Frame(root, pady=5, padx=10)
        self.opt_frame.pack(fill=tk.X)
        
        # [핵심] 파일별로 옵션을 저장하기 위한 딕셔너리 구조로 변경
        self.chk_vars_per_file = {} 
        self.time_window_vars_per_file = {}
        
        self.update_options()

        # --- Bottom Frame: 그래프 ---
        self.plot_frame = tk.Frame(root, bg="white", relief=tk.SUNKEN, bd=2)
        self.plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(self.plot_frame, text="파일 선택 후 모드를 고르고 Run Analysis를 클릭하세요.", bg="white", fg="gray").pack(expand=True)

        # --- 우클릭 메뉴 및 종료 이벤트 ---
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="그림 파일로 저장 (Save as PNG)", command=self.save_as_image)
        self.context_menu.add_command(label="CSV 파일로 저장 (Save as CSV)", command=self.save_as_csv)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def select_file(self):
        file_paths = filedialog.askopenfilenames(title="Select HDF Files", filetypes=(("HDF Files", "*.hdf"), ("All Files", "*.*")))
        if file_paths:
            self.selected_files = file_paths
            display_text = "; ".join([os.path.basename(f) for f in file_paths])
            self.file_path_var.set(display_text)
            self.update_options() # 파일 선택 직후 옵션 패널을 새로고침하여 각 파일별 UI 생성

    def update_options(self, *args):
        for widget in self.opt_frame.winfo_children():
            widget.destroy()
            
        self.chk_vars_per_file.clear()
        self.time_window_vars_per_file.clear()
        mode = self.mode_var.get()
        
        if not self.selected_files:
            tk.Label(self.opt_frame, text="파일을 선택하면 이곳에 개별 옵션이 표시됩니다.", fg="gray").pack(side=tk.LEFT, padx=5)
            return

        # [핵심 변경] 선택된 파일마다 반복문을 돌며 개별 옵션(Frame)을 세로로 층층이 생성
        for file_path in self.selected_files:
            file_name = os.path.basename(file_path)
            
            # 각 파일별 옵션을 담을 하위 프레임 생성
            file_opt_frame = tk.Frame(self.opt_frame)
            file_opt_frame.pack(fill=tk.X, pady=2)
            
            tk.Label(file_opt_frame, text=f"[{file_name}]", font=("Arial", 9, "bold"), width=25, anchor="w").pack(side=tk.LEFT, padx=5)
            
            if mode == "Time vs Throughput":
                self.time_window_vars_per_file[file_name] = tk.StringVar(value="100ms")
                windows = ["10ms", "100ms", "500ms", "1s"]
                for w in windows:
                    rb = tk.Radiobutton(file_opt_frame, text=w, variable=self.time_window_vars_per_file[file_name], value=w, command=self.render_graph)
                    rb.pack(side=tk.LEFT, padx=5)
            else:
                self.chk_vars_per_file[file_name] = {}
                options = []
                if "SNR" in mode:
                    options = ["RX[0]_SNR", "RX[1]_SNR", "RX[2]_SNR", "RX[3]_SNR"]
                elif "RSRP" in mode:
                    options = ["Cell_Quality_RSRP", "RX[0]_RSRP", "RX[1]_RSRP", "RX[2]_RSRP", "RX[3]_RSRP"]
                    
                for opt in options:
                    var = tk.BooleanVar(value=True) 
                    self.chk_vars_per_file[file_name][opt] = var
                    cb = tk.Checkbutton(file_opt_frame, text=opt, variable=var, command=self.render_graph)
                    cb.pack(side=tk.LEFT, padx=5)

    def run_analysis(self):
        if not self.selected_files:
            messagebox.showwarning("Warning", "하나 이상의 HDF 파일을 선택해주세요.")
            return
            
        mode = self.mode_var.get()
        client = QutsClient.QutsClient("L1L2_GUI_Parser")
        
        list_b887 = []
        list_ref = []
        
        for file_path in self.selected_files:
            log_session = None
            try:
                log_session = client.openLogSession([file_path])
                dev_list = log_session.getDeviceList()
                prot_list = log_session.getProtocolList(dev_list[0].deviceHandle)
                diag_handle = next((p.protocolHandle for p in prot_list if p.protocolType == Common.ttypes.ProtocolType.PROT_DIAG), None)
                
                df_b887 = extract_logs_to_dataframe(client, log_session, diag_handle, "0xB887")
                if df_b887 is not None and not df_b887.empty:
                    df_b887['Source_File'] = os.path.basename(file_path)
                    list_b887.append(df_b887)
                    
                if mode == "SNR vs Throughput (0xB8D8)":
                    df_ref = extract_logs_to_dataframe(client, log_session, diag_handle, "0xB8D8")
                    if df_ref is not None and not df_ref.empty:
                        df_ref['Source_File'] = os.path.basename(file_path)
                        list_ref.append(df_ref)
                elif mode == "RSRP vs Throughput (0xB97F)":
                    df_ref = extract_logs_to_dataframe(client, log_session, diag_handle, "0xB97F")
                    if df_ref is not None and not df_ref.empty:
                        df_ref['Source_File'] = os.path.basename(file_path)
                        list_ref.append(df_ref)
                        
            except Exception as e:
                print(f"파일 처리 에러 ({file_path}): {e}")
            finally:
                if log_session:
                    log_session.destroyLogSession()

        if not list_b887:
            messagebox.showerror("Error", "유효한 0xB887 로그를 찾을 수 없습니다.")
            return
            
        self.df_b887_cache = pd.concat(list_b887, ignore_index=True)
        self.df_ref_cache = pd.concat(list_ref, ignore_index=True) if list_ref else None
        
        self.extracted_mode = mode 
        self.render_graph() 

    def render_graph(self):
        if self.extracted_mode != self.mode_var.get() or self.df_b887_cache is None:
            return
            
        plt.close('all') 
        mode = self.mode_var.get()
        fig = None
        csv_df = None
        
        if mode == "Time vs Throughput":
            # 파일별 윈도우 사이즈를 Dictionary 형태로 추출
            file_window_dict = {f_name: var.get() for f_name, var in self.time_window_vars_per_file.items()}
            fig, csv_df = calculate_and_plot_time_series(self.df_b887_cache, file_window_dict)
            
        elif mode == "SNR vs Throughput (0xB8D8)" or mode == "RSRP vs Throughput (0xB97F)":
            # 파일별로 체크된 옵션(True)만 Dictionary 리스트로 추출
            file_cols_dict = {}
            for f_name, opts in self.chk_vars_per_file.items():
                file_cols_dict[f_name] = [col for col, var in opts.items() if var.get()]
            
            title = "SSB SNR vs Throughput" if "SNR" in mode else "RSRP vs Throughput"
            xlabel = "SNR (dB)" if "SNR" in mode else "RSRP (dBm)"
            
            if self.df_ref_cache is not None:
                fig, csv_df = calculate_and_plot_scatter(self.df_b887_cache, self.df_ref_cache, file_cols_dict, title, xlabel)

        if fig:
            self.current_fig = fig
            self.current_csv_df = csv_df
            
            for widget in self.plot_frame.winfo_children():
                widget.destroy()
                
            canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill=tk.BOTH, expand=True)
            canvas_widget.bind("<Button-3>", self.show_context_menu)
            
    def show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def save_as_image(self):
        if self.current_fig:
            filepath = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")])
            if filepath:
                self.current_fig.savefig(filepath, dpi=300, bbox_inches='tight')

    def save_as_csv(self):
        if self.current_csv_df is not None:
            filepath = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV File", "*.csv"), ("All Files", "*.*")])
            if filepath:
                self.current_csv_df.to_csv(filepath, index=False)

    def on_closing(self):
        import sys
        plt.close('all')
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    root = tk.Tk()
    app = LogAnalyzerApp(root)
    root.mainloop()