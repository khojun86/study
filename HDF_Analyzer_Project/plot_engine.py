import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

def calculate_and_plot_time_series(df_b887, file_window_dict):
    """시간축 기반 Throughput, HARQ RV, BLER, MCS, Layer, RB 다중 그래프 렌더링"""
    # 4행 2열의 격자(Grid) 생성 (1, 2번째 줄은 전체 너비 차지)
    fig = plt.figure(figsize=(14, 12))
    gs = gridspec.GridSpec(4, 2, figure=fig)
    
    ax_thr = fig.add_subplot(gs[0, :])   # Throughput
    ax_rv  = fig.add_subplot(gs[1, :])   # [NEW] HARQ RV Profile
    ax_bler = fig.add_subplot(gs[2, 0])  # Total BLER
    ax_mcs = fig.add_subplot(gs[2, 1])   # MCS
    ax_layer = fig.add_subplot(gs[3, 0]) # Layer
    ax_rb = fig.add_subplot(gs[3, 1])    # RB
    
    all_windowed_dfs = []
    if 'Source_File' not in df_b887.columns:
        df_b887['Source_File'] = 'Single_File'
        
    crc_col = 'CRC State' if 'CRC State' in df_b887.columns else 'State'
    
    for file_name, df_group in df_b887.groupby('Source_File'):
        df_group = df_group.copy()
        window_size = file_window_dict.get(file_name, '100ms')
        window_sec = pd.to_timedelta(window_size).total_seconds()
        
        # RV(Redundancy Version) 컬럼 처리 추가
        for col in ['TB Size', 'MCS', 'Num Layers', 'Num Rbs', 'RV']:
            if col in df_group.columns:
                df_group[col] = pd.to_numeric(df_group[col], errors='coerce').fillna(0)
            else:
                df_group[col] = 0
                
        df_group['is_pass'] = df_group[crc_col].astype(str).str.contains('Pass', case=False, na=False)
        df_group['Timestamp'] = pd.to_datetime(df_group['Timestamp'])
        df_time_indexed = df_group.set_index('Timestamp')
        
        # 1. Throughput 계산
        df_pass = df_time_indexed[df_time_indexed['is_pass']]
        df_thr = df_pass.resample(window_size).agg({'TB Size': 'sum'}).fillna(0)
        df_thr['Throughput_Mbps'] = (df_thr['TB Size'] * 8) / window_sec / 1_000_000
        
        # 2. 다중 지표(BLER, MCS 등) 계산
        df_metrics = df_time_indexed.resample(window_size).agg({
            'is_pass': ['count', 'sum'],
            'MCS': 'mean',
            'Num Layers': 'mean',
            'Num Rbs': 'mean'
        }).fillna(0)
        
        df_metrics.columns = ['Total_Pkts', 'Pass_Pkts', 'MCS_Mean', 'Layer_Mean', 'RB_Mean']
        df_metrics['BLER_Pct'] = np.where(df_metrics['Total_Pkts'] > 0, 
                                         (df_metrics['Total_Pkts'] - df_metrics['Pass_Pkts']) / df_metrics['Total_Pkts'] * 100, 0)
        
        # =====================================================================
        # [핵심 추가] HARQ 재전송 차수(RV) 통계 추출
        # =====================================================================
        rv_counts = df_time_indexed.groupby([pd.Grouper(freq=window_size), 'RV']).size().unstack(fill_value=0)
        
        # [오류 수정] groupby 결과의 시간축(Index)을 resample된 df_metrics의 시간축과 강제로 일치시킵니다.
        rv_counts = rv_counts.reindex(df_metrics.index, fill_value=0)
        
        # 안전장치: 특정 구간에 특정 RV(0, 1, 2, 3)가 아예 없을 경우를 대비하여 0으로 채움
        for rv_val in [0, 1, 2, 3]:
            if rv_val not in rv_counts.columns:
                rv_counts[rv_val] = 0
                
        total_rv_pkts = rv_counts.sum(axis=1)
        
        # RV=2 (1차 재전송), RV=3 및 1 (2차 이상 재전송) 비율 계산
        rv2_pct = np.where(total_rv_pkts > 0, rv_counts[2] / total_rv_pkts * 100, 0)
        rv3_plus_pct = np.where(total_rv_pkts > 0, (rv_counts[3] + rv_counts[1]) / total_rv_pkts * 100, 0)
        
        label_name = f'{file_name} ({window_size})'
        
        # 플로팅(Plotting)
        ax_thr.plot(df_thr.index, df_thr['Throughput_Mbps'], linewidth=2.0, label=label_name)
        
        # 다중 파일 겹침을 고려하여 Stacked Area 대신 Line 그래프로 명확히 분리
        ax_rv.plot(rv_counts.index, rv2_pct, linewidth=1.5, label=f'1st ReTx (RV=2) - {file_name}')
        ax_rv.plot(rv_counts.index, rv3_plus_pct, linewidth=1.5, linestyle='--', label=f'2nd+ ReTx (RV=3,1) - {file_name}')
        
        ax_bler.plot(df_metrics.index, df_metrics['BLER_Pct'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_mcs.plot(df_metrics.index, df_metrics['MCS_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_layer.plot(df_metrics.index, df_metrics['Layer_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_rb.plot(df_metrics.index, df_metrics['RB_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        
        # CSV 저장을 위한 데이터 병합 (RV 정보 포함)
        df_metrics['RV2(1st_ReTx)_Pct'] = rv2_pct
        df_metrics['RV3+(2nd_ReTx)_Pct'] = rv3_plus_pct
        
        df_out = pd.concat([df_thr['Throughput_Mbps'], df_metrics], axis=1).reset_index()
        df_out['Source_File'] = file_name
        df_out['Window_Size'] = window_size
        all_windowed_dfs.append(df_out)
    
    # 각 서브플롯 꾸미기
    axes_config = [
        (ax_thr, 'PDSCH MAC Throughput', 'Throughput (Mbps)'),
        (ax_rv, 'HARQ Retransmission Profile', 'ReTx Rate (%)'),
        (ax_bler, 'Total Block Error Rate (BLER)', 'BLER (%)'),
        (ax_mcs, 'Average MCS', 'MCS Index'),
        (ax_layer, 'Average Number of Layers', 'Layers'),
        (ax_rb, 'Average Number of RBs', 'Resource Blocks')
    ]
    
    for ax, title, ylabel in axes_config:
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.7)
            
    ax_thr.legend(loc='upper right', fontsize=9)
    ax_rv.legend(loc='upper right', fontsize=9)
    plt.tight_layout()
    
    final_csv_df = pd.concat(all_windowed_dfs, ignore_index=True) if all_windowed_dfs else None
    return fig, final_csv_df


def calculate_and_plot_scatter(df_thr, df_ref, file_cols_dict, title, xlabel):
    """기준 로그 주기별 산점도 렌더링 (RSRP 0.0 보간, BLER 및 RV 안정화 적용)"""
    fig = plt.figure(figsize=(14, 12)) # 세로로 커진 창 크기에 맞춰 피규어 크기도 살짝 늘렸습니다.
    gs = gridspec.GridSpec(4, 2, figure=fig) # 4행 2열 구조로 변경
    
    ax_thr = fig.add_subplot(gs[0, :])   
    ax_bler = fig.add_subplot(gs[1, 0])  
    ax_mcs = fig.add_subplot(gs[1, 1])   
    ax_layer = fig.add_subplot(gs[2, 0]) 
    ax_rb = fig.add_subplot(gs[2, 1])    
    ax_rv = fig.add_subplot(gs[3, :])    # [추가] 최하단 4행을 가로 전체로 차지하는 RV 도화지
    
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
            
        # RV 컬럼 추가 확인 및 숫자형 변환
        for col in ['TB Size', 'MCS', 'Num Layers', 'Num Rbs', 'RV']:
            df_thr_sub[col] = pd.to_numeric(df_thr_sub.get(col, 0), errors='coerce').fillna(0)
            
        df_thr_sub['is_pass'] = df_thr_sub[crc_col].astype(str).str.contains('Pass', case=False, na=False)
        df_thr_sub['Timestamp'] = pd.to_datetime(df_thr_sub['Timestamp']).astype('datetime64[ns]')
        
        
        df_ref_sub = df_ref_sub.sort_values('Timestamp')
        df_ref_sub.set_index('Timestamp', inplace=True) 
        
        for col in x_cols:
            if col in df_ref_sub.columns:
                df_ref_sub[col] = pd.to_numeric(df_ref_sub[col], errors='coerce')
                df_ref_sub[col] = df_ref_sub[col].replace(0.0, np.nan) 
                df_ref_sub[col] = df_ref_sub[col].interpolate(method='nearest').ffill().bfill()
                
        df_ref_sub.reset_index(inplace=True) 
        
        bins = df_ref_sub['Timestamp'].tolist()
        last_time = max(df_thr_sub['Timestamp'].max(), df_ref_sub['Timestamp'].max()) + pd.Timedelta(seconds=1)
        bins.append(last_time)
        
        df_thr_sub['time_bin'] = pd.cut(df_thr_sub['Timestamp'], bins=bins, right=False)
        
        # 1. 기본 그룹화 연산 (Throughput, BLER, MCS 등)
        grouped = df_thr_sub.groupby('time_bin', observed=False).agg(
            TB_Size_Pass=('TB Size', lambda x: x[df_thr_sub.loc[x.index, 'is_pass']].sum()),
            Total_Pkts=('is_pass', 'count'),
            Pass_Pkts=('is_pass', 'sum'),
            MCS_Mean=('MCS', 'mean'),
            Layer_Mean=('Num Layers', 'mean'),
            RB_Mean=('Num Rbs', 'mean')
        ).reset_index()
        
        # =========================================================================
        # 2. [추가] 산점도를 위한 시간축 기준 RV 카운팅 로직
        # =========================================================================
        rv_counts = df_thr_sub.groupby(['time_bin', 'RV'], observed=False).size().unstack(fill_value=0)
        
        for rv_val in [0, 1, 2, 3]:
            if rv_val not in rv_counts.columns:
                rv_counts[rv_val] = 0
                
        rv_counts = rv_counts.reset_index()
        rv_counts = rv_counts.rename(columns={0: 'RV_0', 1: 'RV_1', 2: 'RV_2', 3: 'RV_3'})
        
        # 기본 grouped 데이터와 RV 카운트 데이터를 시간 구간(time_bin) 기준으로 병합
        grouped = pd.merge(grouped, rv_counts, on='time_bin', how='left').fillna(0)
        # =========================================================================
        
        grouped['ref_time'] = grouped['time_bin'].apply(lambda x: x.left if pd.notnull(x) else pd.NaT)
        grouped['ref_time'] = pd.to_datetime(grouped['ref_time']).astype('datetime64[ns]')
        grouped = grouped.drop(columns=['time_bin'])
        
        df_ref_sub['duration'] = df_ref_sub['Timestamp'].diff().shift(-1).dt.total_seconds().fillna(0.1) 
        df_ref_sub = df_ref_sub[df_ref_sub['duration'] > 0] 
        
        df_merged = pd.merge(df_ref_sub, grouped, left_on='Timestamp', right_on='ref_time', how='left').fillna(0)
        
        # 3. 데이터 안정화 (Rolling Window 5)
        df_merged = df_merged.sort_values('Timestamp')
        df_merged['Roll_Total_Pkts'] = df_merged['Total_Pkts'].rolling(window=5, min_periods=1).sum()
        df_merged['Roll_Pass_Pkts'] = df_merged['Pass_Pkts'].rolling(window=5, min_periods=1).sum()
        
        df_merged['Roll_RV_2'] = df_merged['RV_2'].rolling(window=5, min_periods=1).sum()
        df_merged['Roll_RV_3_plus'] = (df_merged['RV_3'] + df_merged['RV_1']).rolling(window=5, min_periods=1).sum()
        
        # 4. 최종 백분율(%) 계산
        df_merged['BLER_Pct'] = np.where(df_merged['Roll_Total_Pkts'] > 0, 
                                      (df_merged['Roll_Total_Pkts'] - df_merged['Roll_Pass_Pkts']) / df_merged['Roll_Total_Pkts'] * 100, 0)
                                      
        df_merged['RV2_Pct'] = np.where(df_merged['Roll_Total_Pkts'] > 0, 
                                      df_merged['Roll_RV_2'] / df_merged['Roll_Total_Pkts'] * 100, 0)
                                      
        df_merged['RV3_Plus_Pct'] = np.where(df_merged['Roll_Total_Pkts'] > 0, 
                                      df_merged['Roll_RV_3_plus'] / df_merged['Roll_Total_Pkts'] * 100, 0)
        
        df_merged['Throughput_Mbps'] = (df_merged['TB_Size_Pass'] * 8) / df_merged['duration'] / 1_000_000
        df_merged['Source_File'] = file_name
        all_merged_dfs.append(df_merged)
        
        # 5. 서브플롯 렌더링
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
                    
                    # [추가] RV 데이터는 O(원)와 X(엑스) 마커로 시각적으로 구분하여 렌더링
                    ax_rv.scatter(valid_data[col], valid_data['RV2_Pct'], alpha=0.6, color=c, marker='o', label=f'{label} (RV2 1st ReTx)')
                    
                    # [수정] RV3+ 데이터는 값이 0보다 큰 경우에만 필터링하여 출력 (바닥에 깔리는 0점 제거)
                    valid_rv3 = valid_data[valid_data['RV3_Plus_Pct'] > 0]
                    if not valid_rv3.empty:
                        ax_rv.scatter(valid_rv3[col], valid_rv3['RV3_Plus_Pct'], alpha=0.6, color=c, marker='x', label=f'{label} (RV3+ 2nd ReTx)')
                    
                    color_idx += 1

    axes_config = [
        (ax_thr, f'{title} (Throughput)', 'Throughput (Mbps)'),
        (ax_bler, 'Smoothed BLER (Moving Window: 5)', 'BLER (%)'),
        (ax_mcs, 'Average MCS', 'MCS Index'),
        (ax_layer, 'Average Layers', 'Layers'),
        (ax_rb, 'Average RBs', 'Resource Blocks'),
        (ax_rv, 'Smoothed HARQ ReTx Rate (RV2 / RV3+)', 'ReTx Rate (%)') # 추가된 RV 서브플롯
    ]
    
    for ax, sub_title, ylabel in axes_config:
        ax.set_title(sub_title, fontsize=12, fontweight='bold')
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.7)
    
    if all_merged_dfs:
        ax_thr.legend(loc='upper right', fontsize=8, bbox_to_anchor=(1.0, 1.05))
        ax_rv.legend(loc='upper right', fontsize=8, bbox_to_anchor=(1.0, 1.05))
        
    plt.tight_layout()
    
    final_csv_df = pd.concat(all_merged_dfs, ignore_index=True) if all_merged_dfs else None
    return fig, final_csv_df

def prepare_ul_merged_data(df_b883, df_b884):
    """0xB883과 0xB884의 PUSCH 데이터를 시간순으로 병합하여 반환합니다."""
    
    # [핵심 수정] 컬럼 이름이 살짝 달라져도 유연하게 찾을 수 있도록 동적 탐색 함수 적용
    def get_col(df, keywords, default_name):
        for col in df.columns:
            if all(k.lower() in col.lower() for k in keywords):
                return col
        return default_name

    # 0xB883 컬럼 동적 매핑
    b883_mask = get_col(df_b883, ['Phychan', 'Mask'], 'Phychan Bit Mask')
    b883_tx = get_col(df_b883, ['TX Type'], 'TX Type')
    b883_tb = get_col(df_b883, ['TB Size'], 'TB Size (bytes)')
    b883_mcs = next((c for c in df_b883.columns if 'MCS' in c and 'Table' not in c), 'MCS')
    b883_rb = next((c for c in df_b883.columns if 'RB' in c and 'Num' in c), 'Num RBs')
    # [추가] RV 컬럼 추출 로직 추가
    b883_rv = next((c for c in df_b883.columns if 'RV' in c), 'RV Index')
    
    # 0xB884 컬럼 동적 매핑
    b884_type = get_col(df_b884, ['Channel', 'Type'], 'Channel Type')
    b884_pwr = get_col(df_b884, ['Transmit', 'Power'], 'Transmit Power (dB)')
    b884_pl = get_col(df_b884, ['Pathloss'], 'Pathloss (dB)')
    
    # 1. PUSCH 채널만 필터링
    df_883_p = df_b883[df_b883[b883_mask].astype(str).str.contains('PUSCH', case=False, na=False)].copy()
    df_884_p = df_b884[df_b884[b884_type].astype(str).str.contains('PUSCH', case=False, na=False)].copy()
    
    # 2. 통일된 이름으로 컬럼명 강제 변경 (이후 코드 안정성을 위함)
    df_883_p.rename(columns={b883_tx: 'TX Type', b883_tb: 'TB Size (bytes)', b883_mcs: 'MCS', b883_rb: 'Num RBs', b883_rv: 'RV'}, inplace=True)
    df_884_p.rename(columns={b884_pwr: 'Transmit Power (dB)', b884_pl: 'Pathloss (dB)'}, inplace=True)
    
    # 3. 숫자형 변환 및 시간 인덱싱
    for col in ['TB Size (bytes)', 'MCS', 'Num RBs']:
        df_883_p[col] = pd.to_numeric(df_883_p.get(col, 0), errors='coerce').fillna(0)
    for col in ['Transmit Power (dB)', 'Pathloss (dB)']:
        df_884_p[col] = pd.to_numeric(df_884_p.get(col, 0), errors='coerce').fillna(0)
        
    df_883_p['is_new_tx'] = df_883_p['TX Type'].astype(str).str.contains('NEW_TX', case=False, na=False)
    
    df_883_p['Timestamp'] = pd.to_datetime(df_883_p['Timestamp']).astype('datetime64[ns]')
    df_884_p['Timestamp'] = pd.to_datetime(df_884_p['Timestamp']).astype('datetime64[ns]')
    
    # 4. 시간 기준 근사 병합 (가장 가까운 B884 전력 값을 B883 스케줄링에 붙임)
    df_883_p = df_883_p.sort_values('Timestamp')
    df_884_p = df_884_p.sort_values('Timestamp')
    
    df_merged = pd.merge_asof(
        df_883_p, 
        df_884_p[['Timestamp', 'Transmit Power (dB)', 'Pathloss (dB)']], 
        on='Timestamp', 
        direction='nearest',
        tolerance=pd.Timedelta(milliseconds=50) # [수정] 50ms 이내로 넉넉하게 매칭하여 누락 방지
    )
    return df_merged

def calculate_and_plot_ul_scatter(df_b883, df_b884, df_ref, file_cols_dict, title, xlabel):
    """UL 산점도 렌더링 (RSRP 혹은 Pathloss 모드 지원)"""
    fig = plt.figure(figsize=(14, 15))
    gs = gridspec.GridSpec(5, 2, figure=fig) # 5행으로 확장 (Tx Power 추가)
    
    ax_thr = fig.add_subplot(gs[0, :])   
    ax_bler = fig.add_subplot(gs[1, 0])  
    ax_mcs = fig.add_subplot(gs[1, 1])   
    ax_rb = fig.add_subplot(gs[2, 0]) 
    ax_txpwr = fig.add_subplot(gs[2, 1]) # Transmit Power
    ax_rv = fig.add_subplot(gs[3, :])    # RV 카운트 (옵션)
    
    colors = plt.get_cmap('tab10').colors 
    color_idx = 0
    all_merged_dfs = []  # <--- [추가] CSV 저장을 위해 데이터를 모을 빈 바구니 생성
    
    # 1. B883과 B884 먼저 병합
    df_ul_base = prepare_ul_merged_data(df_b883, df_b884)
    
    for file_name in df_ul_base['Source_File'].unique():
        x_cols = file_cols_dict.get(file_name, [])
        if not x_cols: continue
            
        df_ul_sub = df_ul_base[df_ul_base['Source_File'] == file_name].copy()
        df_ref_sub = df_ref[df_ref['Source_File'] == file_name].copy() if df_ref is not None else df_ul_sub.copy()
        
        df_ref_sub['Timestamp'] = pd.to_datetime(df_ref_sub['Timestamp']).astype('datetime64[ns]')
        df_ref_sub = df_ref_sub.sort_values('Timestamp')
        
        # =========================================================================
        # [핵심 추가] 완전히 동일한 타임스탬프 중복 제거 (Bin edges must be unique 에러 방지)
        # =========================================================================
        df_ref_sub = df_ref_sub.drop_duplicates(subset=['Timestamp'])
        
        # 보간 (RSRP 등)
        df_ref_sub.set_index('Timestamp', inplace=True)
        for col in x_cols:
            if col in df_ref_sub.columns:
                df_ref_sub[col] = pd.to_numeric(df_ref_sub[col], errors='coerce').replace(0.0, np.nan)
                df_ref_sub[col] = df_ref_sub[col].interpolate(method='nearest').ffill().bfill()
        df_ref_sub.reset_index(inplace=True)
        
        bins = df_ref_sub['Timestamp'].tolist()
        last_time = max(df_ul_sub['Timestamp'].max(), df_ref_sub['Timestamp'].max()) + pd.Timedelta(seconds=1)
        bins.append(last_time)
        
        # [수정] duplicates='drop' 옵션을 추가하여 혹시 모를 남은 중복 경계값까지 안전하게 무시
        df_ul_sub['time_bin'] = pd.cut(df_ul_sub['Timestamp'], bins=bins, right=False, duplicates='drop')
        grouped = df_ul_sub.groupby('time_bin', observed=False).agg(
            TB_Size_New=('TB Size (bytes)', lambda x: x[df_ul_sub.loc[x.index, 'is_new_tx']].sum()),
            Total_Pkts=('is_new_tx', 'count'),
            New_Pkts=('is_new_tx', 'sum'),
            MCS_Mean=('MCS', 'mean'),
            RB_Mean=('Num RBs', 'mean'),
            TxPwr_Mean=('Transmit Power (dB)', 'mean')
        ).reset_index()

        # =========================================================================
        # [핵심 추가] UL 시간축 기준 RV 카운팅 로직
        # =========================================================================
        # 숫자형 변환 (안전장치)
        df_ul_sub['RV'] = pd.to_numeric(df_ul_sub.get('RV', 0), errors='coerce').fillna(0)
        
        rv_counts = df_ul_sub.groupby(['time_bin', 'RV'], observed=False).size().unstack(fill_value=0)
        for rv_val in [0, 1, 2, 3]:
            if rv_val not in rv_counts.columns:
                rv_counts[rv_val] = 0
                
        rv_counts = rv_counts.reset_index()
        rv_counts = rv_counts.rename(columns={0: 'RV_0', 1: 'RV_1', 2: 'RV_2', 3: 'RV_3'})
        
        grouped = pd.merge(grouped, rv_counts, on='time_bin', how='left').fillna(0)
        # =========================================================================

        grouped['ref_time'] = grouped['time_bin'].apply(lambda x: x.left if pd.notnull(x) else pd.NaT)
        grouped['ref_time'] = pd.to_datetime(grouped['ref_time']).astype('datetime64[ns]')
        
        df_ref_sub['duration'] = df_ref_sub['Timestamp'].diff().shift(-1).dt.total_seconds().fillna(0.1)
        df_merged = pd.merge(df_ref_sub, grouped, left_on='Timestamp', right_on='ref_time', how='left').fillna(0)
        
        df_merged['Roll_Total_Pkts'] = df_merged['Total_Pkts'].rolling(window=5, min_periods=1).sum()
        df_merged['Roll_New_Pkts'] = df_merged['New_Pkts'].rolling(window=5, min_periods=1).sum()
        
        df_merged['Roll_RV_2'] = df_merged['RV_2'].rolling(window=5, min_periods=1).sum()
        df_merged['Roll_RV_3_plus'] = (df_merged['RV_3'] + df_merged['RV_1']).rolling(window=5, min_periods=1).sum()

        df_merged['BLER_Pct'] = np.where(df_merged['Roll_Total_Pkts'] > 0, 
                                      (df_merged['Roll_Total_Pkts'] - df_merged['Roll_New_Pkts']) / df_merged['Roll_Total_Pkts'] * 100, 0)
                                      
        df_merged['RV2_Pct'] = np.where(df_merged['Roll_Total_Pkts'] > 0, 
                                      df_merged['Roll_RV_2'] / df_merged['Roll_Total_Pkts'] * 100, 0)
                                      
        df_merged['RV3_Plus_Pct'] = np.where(df_merged['Roll_Total_Pkts'] > 0, 
                                      df_merged['Roll_RV_3_plus'] / df_merged['Roll_Total_Pkts'] * 100, 0)
                                      
        df_merged['Throughput_Mbps'] = (df_merged['TB_Size_New'] * 8) / df_merged['duration'] / 1_000_000
        
        df_merged['Source_File'] = file_name         # [추가] 어떤 파일의 데이터인지 이름표 붙이기
        all_merged_dfs.append(df_merged)             # [추가] 완성된 데이터를 바구니에 담기

        for col in x_cols:
            if col in df_merged.columns:
                valid_data = df_merged.dropna(subset=[col])
                if not valid_data.empty:
                    label = f'{file_name} - {col}'
                    c = colors[color_idx % len(colors)]
                    
                    ax_thr.scatter(valid_data[col], valid_data['Throughput_Mbps'], label=label, alpha=0.7, edgecolors='k', color=c)
                    ax_bler.scatter(valid_data[col], valid_data['BLER_Pct'], alpha=0.6, edgecolors='k', color=c)
                    ax_mcs.scatter(valid_data[col], valid_data['MCS_Mean'], alpha=0.6, edgecolors='k', color=c)
                    ax_rb.scatter(valid_data[col], valid_data['RB_Mean'], alpha=0.6, edgecolors='k', color=c)
                    ax_txpwr.scatter(valid_data[col], valid_data['TxPwr_Mean'], alpha=0.6, edgecolors='k', color=c)
                    
                    # [추가] 4번째 줄 도화지(ax_rv)에 알맹이 채워넣기 (0% 바닥선 제외 로직 포함)
                    ax_rv.scatter(valid_data[col], valid_data['RV2_Pct'], alpha=0.6, color=c, marker='o', label=f'{label} (RV2 1st ReTx)')
                    valid_rv3 = valid_data[valid_data['RV3_Plus_Pct'] > 0]
                    if not valid_rv3.empty:
                        ax_rv.scatter(valid_rv3[col], valid_rv3['RV3_Plus_Pct'], alpha=0.6, color=c, marker='x', label=f'{label} (RV3+ 2nd ReTx)')
                    
                    color_idx += 1
                    
    # 마지막으로 axes_config 에 ax_rv 타이틀 설정을 잊지 마세요!
    axes_config = [
        (ax_thr, f'{title} (Throughput)', 'Throughput (Mbps)'),
        (ax_bler, 'Smoothed BLER (Moving Window: 5)', 'BLER (%)'),
        (ax_mcs, 'Average MCS', 'MCS Index'),
        (ax_rb, 'Average RBs', 'Resource Blocks'),
        (ax_txpwr, 'Average Transmit Power', 'Tx Power (dBm)'),
        (ax_rv, 'Smoothed HARQ ReTx Rate (RV2 / RV3+)', 'ReTx Rate (%)')
    ]

    # [추가] axes_config를 순회하며 실제로 타이틀과 라벨을 입혀주는 로직
    for ax, sub_title, ylabel in axes_config:
        ax.set_title(sub_title, fontsize=12, fontweight='bold')
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.7)
    
    # [추가] 맨 위 Throughput과 맨 아래 RV 차트에 범례(Legend) 표시
    if all_merged_dfs:
        ax_thr.legend(loc='upper right', fontsize=8, bbox_to_anchor=(1.0, 1.05))
        ax_rv.legend(loc='upper right', fontsize=8, bbox_to_anchor=(1.0, 1.05))
        
    plt.tight_layout()
    
    final_csv_df = pd.concat(all_merged_dfs, ignore_index=True) if all_merged_dfs else None
    return fig, final_csv_df

# plot_engine.py 파일 맨 아래에 추가해 주세요.

def calculate_and_plot_ul_time_series(df_b883, df_b884, file_window_dict):
    """UL 시간축 기반 Throughput, BLER, MCS, RB, Tx Power 다중 그래프 렌더링"""
    # 3행 2열 격자 생성 (첫 줄은 Throughput 전체, 나머지는 2열 분배)
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(3, 2, figure=fig)
    
    ax_thr = fig.add_subplot(gs[0, :])   
    ax_bler = fig.add_subplot(gs[1, 0])  
    ax_mcs = fig.add_subplot(gs[1, 1])   
    ax_rb = fig.add_subplot(gs[2, 0]) 
    ax_txpwr = fig.add_subplot(gs[2, 1]) # DL의 Layer 대신 UL에서는 Tx Power 배치
    
    # 1. 0xB883과 0xB884 데이터 병합
    df_ul_base = prepare_ul_merged_data(df_b883, df_b884)
    all_windowed_dfs = []
    
    for file_name, df_group in df_ul_base.groupby('Source_File'):
        df_group = df_group.copy()
        window_size = file_window_dict.get(file_name, '100ms')
        window_sec = pd.to_timedelta(window_size).total_seconds()
        
        df_time_indexed = df_group.set_index('Timestamp')
        
        # 2. Throughput 계산 (NEW_TX만 합산)
        df_new = df_time_indexed[df_time_indexed['is_new_tx']]
        df_thr = df_new.resample(window_size).agg({'TB Size (bytes)': 'sum'}).fillna(0)
        df_thr['Throughput_Mbps'] = (df_thr['TB Size (bytes)'] * 8) / window_sec / 1_000_000
        
        # 3. 평균 지표 계산
        df_metrics = df_time_indexed.resample(window_size).agg({
            'is_new_tx': ['count', 'sum'],
            'MCS': 'mean',
            'Num RBs': 'mean',
            'Transmit Power (dB)': 'mean'
        }).fillna(0)
        
        df_metrics.columns = ['Total_Tx', 'New_Tx', 'MCS_Mean', 'RB_Mean', 'TxPwr_Mean']
        df_metrics['BLER_Pct'] = np.where(df_metrics['Total_Tx'] > 0, 
                                         (df_metrics['Total_Tx'] - df_metrics['New_Tx']) / df_metrics['Total_Tx'] * 100, 0)
                                         
        label_name = f'{file_name} ({window_size})'
        
        # 4. 플로팅
        ax_thr.plot(df_thr.index, df_thr['Throughput_Mbps'], linewidth=2.0, label=label_name)
        ax_bler.plot(df_metrics.index, df_metrics['BLER_Pct'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_mcs.plot(df_metrics.index, df_metrics['MCS_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_rb.plot(df_metrics.index, df_metrics['RB_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        ax_txpwr.plot(df_metrics.index, df_metrics['TxPwr_Mean'], linewidth=1.5, alpha=0.8, label=label_name)
        
        df_out = pd.concat([df_thr['Throughput_Mbps'], df_metrics], axis=1).reset_index()
        df_out['Source_File'] = file_name
        df_out['Window_Size'] = window_size
        all_windowed_dfs.append(df_out)
        
    axes_config = [
        (ax_thr, 'PUSCH MAC Throughput', 'Throughput (Mbps)'),
        (ax_bler, 'Total UL BLER (ReTx Rate)', 'BLER (%)'),
        (ax_mcs, 'Average MCS', 'MCS Index'),
        (ax_rb, 'Average Number of RBs', 'Resource Blocks'),
        (ax_txpwr, 'Average Transmit Power', 'Tx Power (dBm)')
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