import os
import sys
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# 자체 모듈 임포트
from log_parser import extract_logs_to_dataframe
from plot_engine import calculate_and_plot_time_series, calculate_and_plot_scatter
from plot_engine import prepare_ul_merged_data, calculate_and_plot_ul_scatter
from plot_engine import calculate_and_plot_ul_time_series

# QUTS 모듈 임포트 (API 경로는 log_parser.py에서 이미 추가됨)
try:
    import QutsClient
    import Common.ttypes
except ImportError as e:
    print(f"QUTS 모듈 임포트 실패 (gui_app): {e}")

class LogAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HDF Log Analyzer - Multi-Tab Interface")
        self.root.state('zoomed')
        # 창의 우측 상단 [X] 버튼을 눌렀을 때 on_closing 함수가 실행되도록 설정
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.selected_files = [] 
        self.extracted_mode = "" 
        self.df_b887_cache = None
        self.df_ref_cache = None
        self.current_fig = None
        self.current_csv_df = None
        
        # ---------------------------------------------------------
        # [Global] Top Frame: 파일 선택 
        # ---------------------------------------------------------
        top_frame = tk.Frame(root, pady=10, padx=10)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="HDF Files: ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.file_path_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.file_path_var, width=80, state='readonly').pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text="Browse...", command=self.select_file).pack(side=tk.LEFT)

        # ---------------------------------------------------------
        # [Notebook] 탭 컨트롤 생성
        # ---------------------------------------------------------
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.tab_dl = tk.Frame(self.notebook)
        self.notebook.add(self.tab_dl, text="   DL link curve   ")
        
        self.tab_ul = tk.Frame(self.notebook)
        self.notebook.add(self.tab_ul, text="   UL link curve   ")

        # =========================================================
        # [Tab 1 - DL] DL link curve 탭 내부 UI 구성
        # =========================================================
        mid_frame = tk.Frame(self.tab_dl, pady=10, padx=10)
        mid_frame.pack(fill=tk.X)
        tk.Label(mid_frame, text="Analysis Mode: ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="Time vs Throughput")
        self.mode_var.trace("w", self.update_options)
        
        modes = ["Time vs Throughput", "SNR vs Throughput (0xB8D8)", "RSRP vs Throughput (0xB97F)"]
        for mode in modes:
            tk.Radiobutton(mid_frame, text=mode, variable=self.mode_var, value=mode).pack(side=tk.LEFT, padx=5)
            
        tk.Button(mid_frame, text="Run Analysis", command=self.run_analysis, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side=tk.RIGHT, padx=20)

        self.opt_frame = tk.Frame(self.tab_dl, pady=5, padx=10)
        self.opt_frame.pack(fill=tk.X)
        
        self.chk_vars_per_file = {} 
        self.time_window_vars_per_file = {}
        self.update_options()

        self.plot_frame = tk.Frame(self.tab_dl, bg="white", relief=tk.SUNKEN, bd=2)
        self.plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(self.plot_frame, text="파일 선택 후 모드를 고르고 Run Analysis를 클릭하세요.", bg="white", fg="gray").pack(expand=True)

        # =========================================================
        # [Tab 2 - UL] UL link curve 탭 내부 UI 구성 (새로 추가)
        # =========================================================
        ul_mid_frame = tk.Frame(self.tab_ul, pady=10, padx=10)
        ul_mid_frame.pack(fill=tk.X)
        tk.Label(ul_mid_frame, text="UL Analysis Mode: ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        self.ul_mode_var = tk.StringVar(value="Time vs Throughput")
        self.ul_mode_var.trace("w", self.update_ul_options)
        
        ul_modes = ["Time vs Throughput", "Pathloss vs Throughput (0xB884)", "RSRP vs Throughput (0xB97F)"]
        for mode in ul_modes:
            tk.Radiobutton(ul_mid_frame, text=mode, variable=self.ul_mode_var, value=mode).pack(side=tk.LEFT, padx=5)
            
        tk.Button(ul_mid_frame, text="Run UL Analysis", command=self.run_ul_analysis, bg="#2196F3", fg="white", font=("Arial", 10, "bold")).pack(side=tk.RIGHT, padx=20)

        self.ul_opt_frame = tk.Frame(self.tab_ul, pady=5, padx=10)
        self.ul_opt_frame.pack(fill=tk.X)
        
        self.ul_chk_vars_per_file = {} 
        self.ul_time_window_vars_per_file = {}
        self.update_ul_options()

        self.ul_plot_frame = tk.Frame(self.tab_ul, bg="white", relief=tk.SUNKEN, bd=2)
        self.ul_plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(self.ul_plot_frame, text="파일 선택 후 모드를 고르고 Run UL Analysis를 클릭하세요.", bg="white", fg="gray").pack(expand=True)
        

    def select_file(self):
        file_paths = filedialog.askopenfilenames(title="Select HDF Files", filetypes=(("HDF Files", "*.hdf"), ("All Files", "*.*")))
        if file_paths:
            self.selected_files = file_paths
            display_text = "; ".join([os.path.basename(f) for f in file_paths])
            self.file_path_var.set(display_text)
            self.update_options()

    def update_options(self, *args):
        for widget in self.opt_frame.winfo_children():
            widget.destroy()
            
        self.chk_vars_per_file.clear()
        self.time_window_vars_per_file.clear()
        mode = self.mode_var.get()
        
        if not self.selected_files:
            tk.Label(self.opt_frame, text="파일을 선택하면 이곳에 개별 옵션이 표시됩니다.", fg="gray").pack(side=tk.LEFT, padx=5)
            return

        for file_path in self.selected_files:
            file_name = os.path.basename(file_path)
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
            file_window_dict = {f_name: var.get() for f_name, var in self.time_window_vars_per_file.items()}
            fig, csv_df = calculate_and_plot_time_series(self.df_b887_cache, file_window_dict)
            
        elif mode == "SNR vs Throughput (0xB8D8)" or mode == "RSRP vs Throughput (0xB97F)":
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

    def update_ul_options(self, *args):
        for widget in self.ul_opt_frame.winfo_children():
            widget.destroy()
            
        self.ul_chk_vars_per_file.clear()
        self.ul_time_window_vars_per_file.clear()
        mode = self.ul_mode_var.get()
        
        if not self.selected_files:
            tk.Label(self.ul_opt_frame, text="파일을 선택하면 이곳에 개별 옵션이 표시됩니다.", fg="gray").pack(side=tk.LEFT, padx=5)
            return

        for file_path in self.selected_files:
            file_name = os.path.basename(file_path)
            file_opt_frame = tk.Frame(self.ul_opt_frame)
            file_opt_frame.pack(fill=tk.X, pady=2)
            
            tk.Label(file_opt_frame, text=f"[{file_name}]", font=("Arial", 9, "bold"), width=25, anchor="w").pack(side=tk.LEFT, padx=5)
            
            if mode == "Time vs Throughput":
                self.ul_time_window_vars_per_file[file_name] = tk.StringVar(value="100ms")
                windows = ["10ms", "100ms", "500ms", "1s"]
                for w in windows:
                    rb = tk.Radiobutton(file_opt_frame, text=w, variable=self.ul_time_window_vars_per_file[file_name], value=w, command=self.render_ul_graph)
                    rb.pack(side=tk.LEFT, padx=5)
            else:
                self.ul_chk_vars_per_file[file_name] = {}
                options = []
                if "Pathloss" in mode:
                    options = ["Pathloss (dB)"]
                elif "RSRP" in mode:
                    options = ["Cell_Quality_RSRP", "RX[0]_RSRP", "RX[1]_RSRP", "RX[2]_RSRP", "RX[3]_RSRP"]
                    
                for opt in options:
                    var = tk.BooleanVar(value=True) 
                    self.ul_chk_vars_per_file[file_name][opt] = var
                    cb = tk.Checkbutton(file_opt_frame, text=opt, variable=var, command=self.render_ul_graph)
                    cb.pack(side=tk.LEFT, padx=5)

    def run_ul_analysis(self):
        # DL 분석과 유사하게 0xB883, 0xB884, 0xB97F를 추출하는 로직입니다.
        if not self.selected_files:
            messagebox.showwarning("Warning", "HDF 파일을 선택해주세요.")
            return
            
        mode = self.ul_mode_var.get()
        client = QutsClient.QutsClient("L1L2_GUI_Parser_UL")
        
        list_b883, list_b884, list_b97f = [], [], []
        
        for file_path in self.selected_files:
            log_session = None
            try:
                log_session = client.openLogSession([file_path])
                dev_list = log_session.getDeviceList()
                prot_list = log_session.getProtocolList(dev_list[0].deviceHandle)
                diag_handle = next((p.protocolHandle for p in prot_list if p.protocolType == Common.ttypes.ProtocolType.PROT_DIAG), None)
                
                # 1. 0xB883 (MAC UL Schedule - TB Size, MCS, RB, TX Type 등)
                df_b883 = extract_logs_to_dataframe(client, log_session, diag_handle, "0xB883")
                if df_b883 is not None and not df_b883.empty:
                    df_b883['Source_File'] = os.path.basename(file_path)
                    list_b883.append(df_b883)
                    
                # 2. 0xB884 (MAC UL Power Control - Tx Power, Pathloss)
                df_b884 = extract_logs_to_dataframe(client, log_session, diag_handle, "0xB884")
                if df_b884 is not None and not df_b884.empty:
                    df_b884['Source_File'] = os.path.basename(file_path)
                    list_b884.append(df_b884)
                    
                # 3. 0xB97F (RSRP 모드일 때만 추출)
                if mode == "RSRP vs Throughput (0xB97F)":
                    df_b97f = extract_logs_to_dataframe(client, log_session, diag_handle, "0xB97F")
                    if df_b97f is not None and not df_b97f.empty:
                        df_b97f['Source_File'] = os.path.basename(file_path)
                        list_b97f.append(df_b97f)
                        
            except Exception as e:
                print(f"파일 처리 에러 ({file_path}): {e}")
            finally:
                if log_session:
                    log_session.destroyLogSession()

        self.df_b883_cache = pd.concat(list_b883, ignore_index=True) if list_b883 else None
        self.df_b884_cache = pd.concat(list_b884, ignore_index=True) if list_b884 else None
        self.df_b97f_cache = pd.concat(list_b97f, ignore_index=True) if list_b97f else None
        
        self.ul_extracted_mode = mode 
        self.render_ul_graph()
        
    def render_ul_graph(self):
        if self.ul_extracted_mode != self.ul_mode_var.get() or self.df_b883_cache is None:
            return
            
        plt.close('all') 
        mode = self.ul_mode_var.get()
        fig = None
        csv_df = None
        
        # [수정됨] Time vs Throughput 모드 동작 연결
        if mode == "Time vs Throughput":
            # 파일별로 설정된 윈도우 사이즈(10ms, 100ms 등)를 가져옵니다.
            file_window_dict = {f_name: var.get() for f_name, var in self.ul_time_window_vars_per_file.items()}
            
            # 새로 만든 UL 시간축 함수 호출!
            fig, csv_df = calculate_and_plot_ul_time_series(self.df_b883_cache, self.df_b884_cache, file_window_dict)
            
        elif "Pathloss" in mode or "RSRP" in mode:
            file_cols_dict = {}
            for f_name, opts in self.ul_chk_vars_per_file.items():
                file_cols_dict[f_name] = [col for col, var in opts.items() if var.get()]
            
            title = "Pathloss vs Throughput" if "Pathloss" in mode else "RSRP vs Throughput"
            xlabel = "Pathloss (dB)" if "Pathloss" in mode else "RSRP (dBm)"
            
        # [핵심 수정] Pathloss 모드일 때는 None을 전달하여 엔진 내부의 자체 병합 데이터를 기준축으로 쓰도록 유도
            df_ref = None if "Pathloss" in mode else self.df_b97f_cache
            
            # df_ref가 None이더라도 Pathloss 모드라면 무조건 실행되도록 조건 변경
            if df_ref is not None or "Pathloss" in mode:
                fig, csv_df = calculate_and_plot_ul_scatter(
                    self.df_b883_cache, self.df_b884_cache, df_ref, file_cols_dict, title, xlabel
                )

        if fig:
            self.current_fig = fig
            self.current_csv_df = csv_df
            
            for widget in self.ul_plot_frame.winfo_children():
                widget.destroy()
                
            canvas = FigureCanvasTkAgg(fig, master=self.ul_plot_frame)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill=tk.BOTH, expand=True)
            # [수정] Matplotlib의 네이티브 마우스 이벤트로 우클릭(button == 3) 감지
            canvas.mpl_connect('button_press_event', self.on_plot_right_click)

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
        if messagebox.askokcancel("Quit", "정말 프로그램을 종료하시겠습니까?"):
            try:
                # 1. Matplotlib 켜져 있는 창들 전부 닫기
                plt.close('all')
            
                # 2. Tkinter 창 메인루프 종료 및 루트 파괴
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            finally:
                # 3. [핵심] 파이썬 디버거 및 백그라운드 스레드까지 깔끔하게 강제 종료
                os._exit(0)

    def on_plot_right_click(self, event):
        # event.button == 3 은 마우스 우클릭을 의미합니다.
        if event.button == 3:
            # 팝업 메뉴 생성
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(label="Export to CSV", command=self.export_current_data)
            menu.add_command(label="Save Plot as Image", command=self.export_current_image) # <--- [추가] 이미지 저장 메뉴

            # 현재 마우스 커서 위치에 메뉴 띄우기
            menu.post(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def export_current_data(self):
        from tkinter import filedialog, messagebox
        
        if hasattr(self, 'current_csv_df') and self.current_csv_df is not None:
            # 저장할 파일 경로 묻기
            file_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                title="Save Plot Data as CSV"
            )
            if file_path:
                try:
                    self.current_csv_df.to_csv(file_path, index=False)
                    messagebox.showinfo("Export Success", f"성공적으로 저장되었습니다.\n{file_path}")
                except Exception as e:
                    messagebox.showerror("Export Error", f"저장 중 오류가 발생했습니다.\n{e}")
        else:
            messagebox.showwarning("Warning", "내보낼 데이터가 없습니다.")

    def export_current_image(self):
        from tkinter import filedialog, messagebox
        
        if hasattr(self, 'current_fig') and self.current_fig is not None:
            # 저장할 파일 경로 묻기
            file_path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg"), ("All files", "*.*")],
                title="Save Plot as Image"
            )
            if file_path:
                try:
                    # dpi=300으로 고화질 저장, bbox_inches='tight'로 불필요한 여백 제거
                    self.current_fig.savefig(file_path, dpi=300, bbox_inches='tight')
                    messagebox.showinfo("Export Success", f"그래프가 성공적으로 저장되었습니다.\n{file_path}")
                except Exception as e:
                    messagebox.showerror("Export Error", f"이미지 저장 중 오류가 발생했습니다.\n{e}")
        else:
            messagebox.showwarning("Warning", "저장할 그래프가 없습니다.")