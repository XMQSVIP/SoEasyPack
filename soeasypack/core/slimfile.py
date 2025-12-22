"""
项目瘦身
@author: xmqsvip
Created on 2024-11-30
"""

import os
import csv
import site
import sys
import time
import shutil
import ctypes
import subprocess
from pathlib import Path

from .ast_find_depend import analyze_depends
from .my_logger import my_logger


def is_admin():
    try:
        # 检查是否有管理员权限
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def check_dependency_files(main_run_path, project_dir, check_dir=None, pack_mode=0,
                           monitoring_time=18, except_packages=None, delay_time=3):
    """
    检查依赖文件
    """

    current_dir = Path(__file__).parent.parent
    procmon_path = current_dir.joinpath('dep_exe/Procmon64.exe')
    pmc_base_path = current_dir.joinpath('dep_exe/ProcmonConfiguration.pmc')
    procmon_log_path = Path(project_dir).joinpath('procmon_log.pml')
    csv_log_path = Path(project_dir).joinpath('procmon_log.csv')
    dependency_file_csv = Path(project_dir).joinpath("dependency.csv")
    if pack_mode == 0:
        dependency_file_csv = Path(project_dir).joinpath("dependency_fast.csv")
    if dependency_file_csv.exists():
        my_logger.info('已存在依赖文件清单表，跳过依赖文件检查')
        dependency_files = get_dependency_list(dependency_file_csv, pack_mode=pack_mode)
        return dependency_files
    if pack_mode == 3:
        my_logger.info('分析依赖文件...')
        dependency_files = analyze_depends(main_run_path, except_pkgs=except_packages)

        with open(dependency_file_csv, mode='w', newline='', encoding='utf-8') as fp:
            csv_writer = csv.writer(fp)
            for i in dependency_files:
                csv_writer.writerow([i])
        return dependency_files

    my_logger.info('当你的项目稍后自动运行后，请进行一些必要的功能操作：如点击运行按钮等,否则可能会造成依赖缺失')
    if is_admin():
        delay_time = 1
    else:
        print("以管理员身份打开的编辑器中执行此程序可避免弹出用户账户控制窗口提示")
    time.sleep(5)
    if os.path.exists(procmon_log_path):
        os.remove(procmon_log_path)
    my_logger.info(f'准备监控依赖文件，{monitoring_time}秒后自动结束监控')
    cmd = [
        procmon_path,
        "/Minimized",
        "/AcceptEula",
        "/Runtime", str(monitoring_time),
        "/Quiet",
        "/Backingfile", procmon_log_path,
        # "/LoadConfig", pmc_base_path,
    ]

    my_logger.info(f"开始启动监控工具,{delay_time}秒后自动启动你的程序")
    procmon_process = subprocess.Popen(cmd)
    time.sleep(delay_time)
    current_env_py = sys.executable.replace('\\', '/')
    image_path = str(sys.base_prefix).replace('\\', '/') + '/python.exe'

    # 启动你的脚本
    if 'py' in str(Path(main_run_path).suffix):
        if pack_mode == 0:
            main_run_cmd = [current_env_py, main_run_path]
            if not os.path.exists(image_path):
                my_logger.error(f'未找到{image_path}')
                sys.exit()
        else:
            python_exe_path = str(Path(project_dir).joinpath('rundep/python.exe'))
            pythonw_exe_path = str(Path(project_dir).joinpath('rundep/pythonw.exe'))
            if os.path.exists(python_exe_path):
                main_run_cmd = [python_exe_path, main_run_path]
                image_path = python_exe_path
            elif os.path.exists(pythonw_exe_path):
                main_run_cmd = [pythonw_exe_path, main_run_path]
                image_path = pythonw_exe_path
            else:
                my_logger.warning(f'未找到{project_dir}/rundep文件夹中的python.exe，使用当前环境的python运行脚本')
                main_run_cmd = [current_env_py, main_run_path]

    else:
        main_run_cmd = main_run_path
        image_path = main_run_path

    os.chdir(os.path.dirname(main_run_path))
    my_logger.info(f"启动你的程序:{main_run_path}")
    main_run_process = subprocess.Popen(main_run_cmd)
    time.sleep(monitoring_time)
    main_run_process.kill()

    procmon_process.wait()
    my_logger.info("开始保存日志")
    cmd = [
        procmon_path,
        "/Minimized",
        "/AcceptEula",
        "/Quiet",
        "/NoConnect",
        "/OpenLog", procmon_log_path,
        "/SaveAs", csv_log_path,
        "/LoadConfig", pmc_base_path,
    ]
    procmon_process = subprocess.Popen(cmd)
    procmon_process.wait()

    while True:
        if Path.exists(csv_log_path):
            break
        time.sleep(1)

    dependency_files = get_dependency_list(csv_log_path, image_path, check_dir, pack_mode)

    # for i in dependency_files:
    #     if 'webview' in i:
    #         for root, dirs, files in os.walk(f"{site_pkg_dir}/webview/lib/runtimes"):
    #             for file in files:
    #                 file_path = os.path.join(root, file)
    #                 depends.add(file_path)
    # # 排除用户指定的第三方依赖包
    if except_packages:
        ready_remove_list = []
        for i in dependency_files:
            for except_package in except_packages:
                if f"site-packages/{except_package}" in i:
                    ready_remove_list.append(i)
        for i in ready_remove_list:
            dependency_files.remove(i)

    # 查找是否有以.pth结尾的文件
    sp_path = None
    current_env_py = sys.executable.replace('\\', '/')
    sp_path_list = site.getsitepackages()
    for i in sp_path_list:
        if 'site-packages' in i:
            sp_path = i
            break
    pth_files = [f for f in Path(sp_path).iterdir() if f.suffix == '.pth']
    dependency_files.update(pth_files)

    if dependency_files:
        with open(dependency_file_csv, mode='w', newline='', encoding='utf-8') as fp:
            csv_writer = csv.writer(fp)
            for i in dependency_files:
                csv_writer.writerow([i])
    try:
        os.remove(procmon_log_path)
        os.remove(csv_log_path)
    except Exception as e:
        my_logger.error(f"删除日志文件失败:{e}")

    return dependency_files


def get_dependency_list(csv_log_path, image_path=None, check_dir=None, pack_mode=0):
    my_logger.info('开始分析依赖文件...')
    if pack_mode == 0:
        base_env_dir = sys.base_prefix.lower().replace('\\', '/')
        current_env_dir = sys.prefix.lower().replace('\\', '/')
        if base_env_dir == current_env_dir:
            check_dir = base_env_dir
        else:
            check_dir = [base_env_dir, current_env_dir]

    dependency_files = set()
    with open(csv_log_path, encoding='utf-8') as fp:
        csvreader = csv.reader(fp)
        if check_dir and image_path:
            image_path = image_path.lower().replace('\\', '/')
            if isinstance(check_dir, list):
                for row in csvreader:
                    cell_value = row[0].replace('\\', '/')
                    cell_value_ = cell_value.lower()
                    cell_value_2 = row[1].replace('\\', '/').lower()
                    if cell_value_2 == image_path and cell_value_ and os.path.isfile(cell_value_) and (
                            '__pycache__' not in cell_value_):
                        if (check_dir[0] in cell_value_) or (check_dir[1] in cell_value_):
                            dependency_files.add(cell_value)
            else:
                check_dir = check_dir.lower().replace('\\', '/')
                for row in csvreader:
                    cell_value = row[0].replace('\\', '/')
                    cell_value_ = cell_value.lower()
                    cell_value_2 = row[1].replace('\\', '/').lower()
                    if cell_value_2 == image_path and cell_value_ and os.path.isfile(cell_value_) and (
                            check_dir in cell_value_) and ('__pycache__' not in cell_value_):
                        dependency_files.add(cell_value)
        else:
            # 读取的是依赖文件清单表，跳过查找依赖文件
            for row in csvreader:
                dependency_files.add(row[0])

    return dependency_files


def move_files(check_dir, project_dir, dependency_files):
    my_logger.info('开始瘦身...')
    removed_file_dir = os.path.join(project_dir, "removed_file")

    moved_file_num = 0
    removed_size = 0

    for root, dirs, files in os.walk(check_dir):
        if "rundep/AppData" in root:
            continue
        for filename in files:
            src_file = str(os.path.join(root, filename)).replace('\\', '/')
            if src_file in dependency_files or src_file.endswith('.pth'):
                continue
            else:
                try:
                    # 保持目录结构
                    relative_path = str(os.path.relpath(root, check_dir))
                    dest_folder = os.path.join(removed_file_dir, relative_path)
                    os.makedirs(dest_folder, exist_ok=True)
                    removed_size += os.path.getsize(src_file)
                    # 移动文件
                    shutil.move(src_file, os.path.join(dest_folder, filename))
                    moved_file_num += 1
                except Exception as e:
                    my_logger.error(f"无法移动文件: {src_file}: {e}")

    # 移除空文件夹
    for root, dirs, files in os.walk(project_dir, topdown=False):
        for name in dirs:
            full_path = os.path.join(root, name)
            if not os.listdir(str(full_path)):
                try:
                    os.rmdir(full_path)
                except Exception:
                    pass

    removed_size = f"{removed_size / (1024 * 1024):.2f}"
    my_logger.info(f"瘦身完成，移除了{moved_file_num}个文件, 减小了{removed_size}M")
    if moved_file_num > 0:
        my_logger.info(f"移除的文件保存到了:{removed_file_dir}")


def to_slim_file(main_run_path: str, check_dir: str, project_dir: str = None,
                 monitoring_time: int = 18, pack_mode=1, delay_time: int = 3) -> None:
    """
    项目瘦身
    :param main_run_path: 项目主运行文件路径,py或其它
    :param check_dir: 需要瘦身的目录
    :param project_dir:  项目目录
    :param monitoring_time:  监控工具监控时长（秒）
    :param pack_mode: 若单独使用瘦身功能不必填写
    :param delay_time:  启动监控工具后延时几秒启动用户程序
    :return:
    """

    if project_dir is None:
        project_dir = check_dir

    main_run_path = main_run_path.replace("\\", "/")
    check_dir = check_dir.replace("\\", "/")
    project_dir = project_dir.replace("\\", "/")
    dependency_files = check_dependency_files(main_run_path, project_dir, check_dir, monitoring_time=monitoring_time,
                                              pack_mode=pack_mode, delay_time=delay_time)
    move_files(check_dir, project_dir, dependency_files)
