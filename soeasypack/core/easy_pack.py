"""
简易打包
@author: xmqsvip
Created on 2024-11-30
"""

import json
import os
import py_compile
import random
import string
import subprocess
import sys
import shutil
import fnmatch
import zipfile
from functools import partial
from pathlib import Path
from typing import Literal, TypedDict
from concurrent.futures import as_completed, ThreadPoolExecutor

from .my_logger import my_logger
from .py_to_pyd import to_pyd
from .slimfile import to_slim_file, check_dependency_files


class KwargsType(TypedDict, total=False):
    file_version: str
    product_name: str
    company: str


def copy_file(src, dest):
    if not os.path.exists(dest):
        shutil.copyfile(src, dest)


# 复制目录的并行化版本
def copytree_parallel(src, dest, ignore_func=None):
    if not os.path.exists(dest):
        os.makedirs(dest)

    futures = []
    with ThreadPoolExecutor() as executor:
        for root, dirs, files in os.walk(src):
            dest_dir = os.path.join(dest, str(os.path.relpath(root, src)))
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)

            # 过滤需要忽略的目录和文件
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, pattern) for pattern in ignore_func(root, dirs))]
            files_to_copy = [f for f in files if f not in ignore_func(root, files)]

            for file in files_to_copy:
                futures.append(executor.submit(copy_file, os.path.join(root, file), os.path.join(dest_dir, file)))

    # 等待所有任务完成
    for future in as_completed(futures):
        try:
            future.result()
        except Exception as e:
            my_logger.error(f"复制线程出错: {e}")


def copy_py_env(save_dir, main_run_path=None, pack_mode=0, monitoring_time=18, except_packages=None, embed_exe=False):
    """
    复制 Python环境依赖
    :param save_dir:
    :param main_run_path:
    :param pack_mode:
    :param monitoring_time:
    :param except_packages:
    :param embed_exe:
    :return:
    """

    base_env_dir = Path(sys.base_prefix).resolve()
    current_env_dir = Path(sys.prefix).resolve()
    if current_env_dir == base_env_dir:
        is_go = input(f"当前你的环境：非虚拟环境，{current_env_dir}, 可能会打包无用的依赖文件！若继续操作，请输入Y或y：")
        if is_go.lower() != 'y':
            sys.exit()
    mode_info = ("快速模式", "普通模式", "轻量模式", "ast模式")
    my_logger.info(f"当前模式：{mode_info[pack_mode]}")
    if pack_mode in (0, 3):
        dependency_files = check_dependency_files(main_run_path, save_dir, pack_mode=pack_mode,
                                                  monitoring_time=monitoring_time, except_packages=except_packages)
        if pack_mode == 3 and not embed_exe:
            dependency_files.add(os.path.join(base_env_dir, 'python.exe'))
        rundep_dir = Path.joinpath(Path(save_dir), 'rundep').resolve()

        my_logger.info("复制python环境...")
        with ThreadPoolExecutor() as executor:
            futures = []
            current_env_path = Path(current_env_dir).resolve()
            base_env_path = base_env_dir.resolve()
            for dependency_file in dependency_files:
                dep_path = Path(dependency_file).resolve()
                if current_env_path in dep_path.parents:
                    relative_path = dep_path.relative_to(current_env_path)
                    dependency_file_ = rundep_dir / relative_path
                else:
                    relative_path = dep_path.relative_to(base_env_path)
                    dependency_file_ = rundep_dir / relative_path

                if os.path.exists(dependency_file):
                    to_save_dir = os.path.dirname(dependency_file_)
                    os.makedirs(to_save_dir, exist_ok=True)
                    futures.append(executor.submit(copy_file, dependency_file, dependency_file_))
            # 等待所有复制任务完成
            for future in as_completed(futures):
                try:
                    future.result()  # 获取结果，捕获任务中的异常
                except Exception as e:
                    my_logger.error(f"复制线程出错: {e}")
    elif pack_mode in (1, 2):
        my_logger.info("复制python环境...")
        dest = Path.joinpath(Path(save_dir), 'rundep')

        def ignore_files(src, names, py_exclusions):
            ignored = []
            for name in names:
                if any(fnmatch.fnmatch(name, pattern) for pattern in py_exclusions):
                    ignored.append(name)
            return ignored

        # # 排除复制官方python无用的文件和文件夹
        py_exclusions = ('Scripts', 'Doc', 'LICENSE', 'LICENSE.txt',
                         'NEWS.txt', 'share', 'Tools', 'include', 'venv', 'readme',
                         'site-packages', 'test', '__pycache__', 'lib2to3', 'unittest', 'turtledemo'
                         )

        ignore_func = partial(ignore_files, py_exclusions=py_exclusions)
        copytree_parallel(base_env_dir, dest, ignore_func)
        if pack_mode == 1:
            # # 复制 site-packages
            # # 排除复制site-packages其它无用文件
            py_exclusions = ['__pycache__', 'pip*', '_distutils_hack', 'pkg_resources', 'setuptools*',
                             'distutils-precedence.pth', 'better_exceptions_hook.pth',
                             'py2exe*', 'Pyinstaller*', 'cx_Freeze*', 'nuitka*',
                             'auto_py_to_exe*', 'soeasypack*']
            if except_packages:
                py_exclusions.extend(except_packages)
            ignore_func = partial(ignore_files, py_exclusions=py_exclusions)

            sp_path = Path.joinpath(Path(current_env_dir), 'Lib/site-packages')
            to_sp_path = Path.joinpath(Path(dest), 'Lib/site-packages')
            copytree_parallel(sp_path, to_sp_path, ignore_func)
        else:
            os.makedirs(Path.joinpath(Path(dest), 'Lib/site-packages'), exist_ok=True)

    pyenv_file = Path.joinpath(Path(save_dir), 'rundep/pyvenv.cfg')
    if pyenv_file.exists():
        os.remove(pyenv_file)
    scripts_dir = Path.joinpath(Path(save_dir), 'rundep/Scripts')
    shutil.rmtree(scripts_dir, ignore_errors=True)
    if embed_exe:
        python_exe_path = Path.joinpath(Path(save_dir), 'rundep/python.exe')
        if os.path.exists(python_exe_path):
            os.remove(python_exe_path)


def copy_embed_depend(save_dir, base_env_dir):
    # # 复制运行嵌入exe所需依赖项
    py_files = ('hmac', 'secrets', 'struct', 'base64', 'warnings', 'hashlib', 'random',
                'bisect', 'contextlib', 'zipfile', 'posixpath', 'shutil', 'fnmatch', 'threading',
                '_weakrefset', 'signal')
    not_exists_files = []
    for py_file in py_files:
        to_save_path = Path.joinpath(Path(save_dir), f"rundep/Lib/{py_file}.py")
        if not os.path.exists(to_save_path):
            py_file_path = Path.joinpath(Path(base_env_dir), f"Lib/{py_file}.py")
            if os.path.exists(py_file_path):
                shutil.copyfile(py_file_path, to_save_path)
            else:
                not_exists_files.append(py_file)
    # # python3.12的zipfile是个包不是模块
    for py_file in not_exists_files:
        py_file_dir = Path.joinpath(Path(base_env_dir), f"Lib/{py_file}")
        if py_file_dir.is_dir():
            to_save_dir = Path.joinpath(Path(save_dir), f"rundep/Lib/{py_file}")
            shutil.copytree(py_file_dir, to_save_dir, dirs_exist_ok=True)

    encodings_files = ('cp437', 'gbk')
    for encodings_file in encodings_files:
        encodings_file_path = Path.joinpath(Path(base_env_dir), f"Lib/encodings/{encodings_file}.py")
        to_encodings_file_path = Path.joinpath(Path(save_dir), f"rundep/Lib/encodings/{encodings_file}.py")
        shutil.copyfile(encodings_file_path, to_encodings_file_path)

    multiprocessing_dir = Path.joinpath(Path(base_env_dir), 'Lib/multiprocessing')
    to_multiprocessing_dir = Path.joinpath(Path(save_dir), 'rundep/Lib/multiprocessing')
    shutil.copytree(multiprocessing_dir, to_multiprocessing_dir, dirs_exist_ok=True)

    importlib_dir = Path.joinpath(Path(base_env_dir), 'Lib/importlib')
    to_importlib_dir = Path.joinpath(Path(save_dir), 'rundep/Lib/importlib')
    shutil.copytree(importlib_dir, to_importlib_dir, dirs_exist_ok=True)


def xor_encrypt(file_path, key):
    """
    xor混淆
    :param file_path:
    :param key:
    :return:
    """
    key_bytes = key.encode('utf-8')
    key_length = len(key_bytes)

    with open(file_path, 'r+b') as f:
        data = bytearray(f.read())
        len_data = len(data)

        for i in range(len_data):
            data[i] ^= key_bytes[i % key_length]
        f.seek(0)
        f.write(data)
        f.truncate()


def copy_py_script(main_py_path, save_dir):
    my_logger.info('复制你的脚本目录...')
    relpath_name = None
    main_py_path = main_py_path.replace('\\', '/')
    save_dir = save_dir.replace('\\', '/')
    main_py_dir = os.path.dirname(main_py_path)
    appdata_dir = Path.joinpath(Path(save_dir), 'rundep/AppData')
    if main_py_dir in save_dir:
        relpath_name = os.path.relpath(save_dir, main_py_dir)
        relpath_name = relpath_name.replace('\\', '/').split('/', 1)[0]

    def ignore_save_dir(src, names):
        ignore_names = ['.git', '.svn', '.idea', '__pycache__', 'venv']
        if src == main_py_dir and relpath_name and relpath_name in names:
            ignore_names.append(relpath_name)
        return ignore_names

    shutil.copytree(main_py_dir, appdata_dir, dirs_exist_ok=True, ignore=ignore_save_dir)

    new_main_py_path = os.path.join(appdata_dir, os.path.basename(main_py_path))
    return new_main_py_path


def create_bat(save_dir, embed_exe):
    py_suffix = 'pyc' if embed_exe else 'py'

    # 生成bat脚本
    bat_file_content = fr'''
@echo off
set "current_dir=%cd%"
set "rundep_dir=%current_dir%\rundep"
set "python_path=%rundep_dir%\python.exe"

cd /d "%rundep_dir%\AppData"
start /B "" %python_path% main.{py_suffix}"
'''
    bat_path = Path.joinpath(Path(save_dir), 'run.bat')
    with open(bat_path, 'w', encoding='utf-8') as bat_file:
        bat_file.write(bat_file_content)
    return bat_path


def build_exe(save_dir, hide_cmd: bool = True, exe_name: str = 'main', png_path: str = None,
              embed_exe: bool = False, onefile: bool = False, pack_mode=0, winres_json_path: str = None,
              file_version: str = None, product_name: str = None, company: str = None, uac: bool = False,
              all_pyc_zip: bool = False, pip_source: str = None
              ):
    """
    使用go语言编译
    :param save_dir:
    :param hide_cmd:
    :param exe_name:
    :param png_path:
    :param embed_exe:
    :param onefile:
    :param pack_mode:
    :param winres_json_path:
    :param file_version:
    :param product_name:
    :param company:
    :param uac:
    :param all_pyc_zip:
    :param pip_source:
    :return:
    """

    my_logger.info('生成exe...')
    current_dir = Path(__file__).parent.parent
    go_exe_path = Path.joinpath(current_dir, 'dep_exe/go_env/bin/go.exe')
    winres_path = Path.joinpath(current_dir, 'dep_exe/go_env/go-winres.exe')
    winres_json_source = Path.joinpath(current_dir, 'dep_exe/go_env/winres.json')
    temp_build_dir = Path.joinpath(Path(save_dir), 'temp_build')
    os.makedirs(temp_build_dir, exist_ok=True)
    save_winres_json = Path.joinpath(temp_build_dir, "winres.json")
    dest_go_py_path = Path.joinpath(temp_build_dir, 'go_py.go')
    rundep_dir = Path.joinpath(Path(save_dir), 'rundep')
    if onefile:
        embed_exe = True

    if embed_exe:
        ready_remove_pyc = []
        go_py_path = Path.joinpath(current_dir, 'dep_exe/go_env/go_py_embed.go')
        main_py_path = Path.joinpath(Path(save_dir), 'rundep/AppData/main.pyc')
        with open(main_py_path, mode='rb') as fp:
            main_py_code = fp.read()
            main_py_code_hex = main_py_code.hex()
        os.remove(main_py_path)
        if onefile:
            all_zip_path = Path.joinpath(temp_build_dir, 'rundep.zip')
            with zipfile.ZipFile(all_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(rundep_dir):
                    for file in files:
                        if 'AppData' in root and file.endswith('.pyc'):
                            continue
                        else:
                            full_path = os.path.join(root, file)
                            archive_name = os.path.relpath(full_path, start=rundep_dir)
                            zipf.write(full_path, arcname=archive_name)
        # # 生成密钥
        characters = random.choices(string.ascii_letters + string.digits, k=14)
        xor_key = list(characters) + [random.choice(string.digits), random.choice(string.ascii_letters)]
        random.shuffle(xor_key)
        xor_key = ''.join(xor_key)

        # # 修改go代码
        shutil.copyfile(go_py_path, dest_go_py_path)
        with open(dest_go_py_path, 'r+', encoding='utf-8') as fp:
            go_code = fp.read()
            fp.seek(0)
            py_version = sys.version.replace('.', '', 1).split('.', 1)[0]
            edited_go_code = (go_code.replace('python3.dll', f'python{py_version}.dll').
                              replace('main_pycode', main_py_code_hex).
                              replace('xor_key', xor_key, 1))
            if onefile:
                edited_go_code = (edited_go_code.replace('embed soeasypack.sz',
                                                         'embed soeasypack.sz rundep.zip', 1).
                                  replace('onefile bool = false', 'onefile bool = true', 1)
                                  )
            elif pack_mode == 2:
                if not pip_source:
                    pip_source = 'https://pypi.tuna.tsinghua.edu.cn/simple'
                edited_go_code = (edited_go_code.replace(
                    'var packmode int = 0', 'var packmode int = 2', 1).replace(
                    'pip_source', pip_source
                ))
            fp.write(edited_go_code)
            fp.truncate()
        # # 生成zip归档
        zip_path = Path.joinpath(temp_build_dir, 'soeasypack.sz')
        app_data_dir = Path.joinpath(Path(save_dir), 'rundep')
        if all_pyc_zip:
            # # 压缩python自带的模块
            python_zip_path = Path.joinpath(Path(save_dir), f'rundep/python{py_version}.zip')
            lib_dir = Path.joinpath(Path(save_dir), 'rundep/Lib')
            with zipfile.ZipFile(python_zip_path, 'w') as zip_fp:
                for root, dirs, files in os.walk(lib_dir):
                    for file in files:
                        if file.endswith('.pyc') and 'site-packages' not in root:
                            full_path = os.path.join(root, file)
                            archive_name = os.path.relpath(full_path, start=lib_dir)
                            zip_fp.write(full_path, arcname=archive_name)
                            ready_remove_pyc.append(full_path)

        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zip_fp:
            nn = 0
            for root, dirs, files in os.walk(app_data_dir):
                if nn == 0:
                    if all_pyc_zip:
                        dirs[:] = ['AppData', 'Lib']
                    else:
                        dirs[:] = ['AppData']
                    nn = 1

                for file in files:
                    if file.endswith('.pyc'):
                        full_path = os.path.join(root, file)
                        archive_name = os.path.relpath(full_path, start=app_data_dir)
                        if 'AppData' in root or (all_pyc_zip and 'site-packages' in root):
                            archive_name = archive_name.replace('Lib\\site-packages\\', '').replace('AppData\\', '')
                            zip_fp.write(full_path, arcname=archive_name)
                            ready_remove_pyc.append(full_path)

        xor_encrypt(zip_path, xor_key)
        for i in ready_remove_pyc:
            if os.path.exists(i):
                os.remove(i)
    else:
        go_py_path = Path.joinpath(current_dir, 'dep_exe/go_env/go_py.go')
        shutil.copyfile(go_py_path, dest_go_py_path)
        with open(dest_go_py_path, 'r+', encoding='utf-8') as fp:
            go_code = fp.read()
            fp.seek(0)
            py_version = sys.version.replace('.', '', 1).split('.', 1)[0]
            fp.write(go_code.replace('python3.dll', f'python{py_version}.dll'))
            fp.truncate()

    if png_path and os.path.exists(png_path):
        copy_icon_path = Path.joinpath(temp_build_dir, f'{os.path.basename(png_path)}')
        shutil.copyfile(png_path, copy_icon_path)
        icon_name = os.path.basename(png_path)
    else:
        my_logger.warning("未找到图标文件，将使用默认图标")
        icon_name = ''

    if not winres_json_path:
        shutil.copyfile(winres_json_source, save_winres_json)
        winres_json = json.load(open(winres_json_source, encoding='utf-8'))
        if icon_name:
            winres_json["RT_GROUP_ICON"]["APP"]["0000"].append(icon_name)
        if file_version:
            winres_json["RT_VERSION"]["#1"]["0000"]["fixed"]["file_version"] = file_version
        if product_name:
            winres_json["RT_VERSION"]["#1"]["0000"]["info"]["0409"]["ProductName"] = product_name
        if company:
            winres_json["RT_VERSION"]["#1"]["0000"]["info"]["0409"]["CompanyName"] = company
        if uac:
            winres_json["RT_MANIFEST"]["#1"]["0409"]["execution-level"] = "requireAdministrator"
        json.dump(winres_json, open(save_winres_json, 'w', encoding='utf-8'), indent=4)
    else:
        if not os.path.exists(winres_json_path):
            raise FileNotFoundError(f'未找到winres.json文件:{winres_json_path}')
        shutil.copyfile(winres_json_path, save_winres_json)

    os.chdir(temp_build_dir)
    with open('go.mod', mode='w', encoding='utf-8') as fp:
        go_require = '''
module go_py
go 1.23
'''
        fp.write(go_require)

    pro = subprocess.Popen(f'{winres_path} make --in {save_winres_json}')
    pro.wait()
    save_exe_path = Path.joinpath(Path(save_dir), exe_name + '.exe')
    is_show_cmd = '-ldflags "-s -w -H=windowsgui"' if hide_cmd else '-ldflags "-s -w"'

    command = f'{go_exe_path} build {is_show_cmd} -buildvcs=false -o {save_exe_path}'
    build_process = subprocess.Popen(command)
    build_process.wait()
    os.chdir(save_dir)
    shutil.rmtree(temp_build_dir)
    # 移除空文件夹
    for root, dirs, files in os.walk(rundep_dir, topdown=False):
        for name in dirs:
            full_path = os.path.join(root, name)
            if not os.listdir(str(full_path)):
                try:
                    os.rmdir(full_path)
                except Exception:
                    pass


def py_to_pyc(dest_dir, optimize):
    my_logger.info(f'开始将py文件转成pyc文件, pyc优化级别:{optimize}')
    ready_remove_dirs = []
    ready_remove_files = []

    for root, dirs, files in os.walk(dest_dir):
        if '__pycache__' in root:
            ready_remove_dirs.append(root)
            continue
        for file in files:
            if 'site-pack' in root and (('config' in file) or ('WmDefault' in file)):
                # # cv2会读取config.py文件, 跳过tcl的WmDefault(缩进有问题)
                continue
            if file.endswith('.py'):
                py_file = os.path.join(root, file)
                try:
                    py_compile.compile(py_file, cfile=py_file + 'c', quiet=1, optimize=optimize)
                    ready_remove_files.append(py_file)
                except Exception as e:
                    my_logger.error(f"{py_file} 转pyc时发生错误: {e}")

    # 删除成功编译的py文件和__pycache__目录
    for root in ready_remove_dirs:
        shutil.rmtree(root)
    for file in ready_remove_files:
        os.remove(file)


def to_pack(main_py_path: str, save_dir: str = None,
            exe_name: str = 'main', png_path: str = None, hide_cmd: bool = True,
            pack_mode: Literal[0, 1, 2, 3] = 0, force_copy_env: bool = False,
            auto_py_pyc: bool = True, pyc_optimize: Literal[-1, 0, 1, 2] = 1,
            auto_py_pyd: bool = False, embed_exe: bool = False, onefile: bool = False,
            monitoring_time: int = 18, uac: bool = False, requirements_path: str = None,
            except_packages: [str] = None, winres_json_path: str = None, delay_time: int = 3,
            all_pyc_zip: bool = False, pip_source: str = None,
            **kwargs: KwargsType) -> None:
    """
    :param main_py_path:主入口py文件路径
    :param save_dir:打包保存目录(默认为桌面目录)
    :param exe_name:生成的exe文件名字
    :param png_path: exe图标路径
    :param hide_cmd:是否显示控制台窗口
    :param pack_mode:0/快速打包模式：监控分析依赖文件，然后复制依赖，不用再瘦身，适合非虚拟环境（虚拟环境也可）。
    1/普通模式：先复制python环境依赖包，然后监控分析依赖文件，再进行项目瘦身,会保存被移除的文件，
    因为会复制整个site-packages文件夹，所以不建议在非虚拟环境使用，
    2/轻量模式，不复制site-packages文件夹，第一次启动程序自动pip下载依赖包
    3/ast模式
    :param force_copy_env: 强行每次复制python环境依赖包
    :param auto_py_pyc：知否把所有py转为pyc
    :param pyc_optimize: pyc优化级别，
    -1：使用当前解释器的优化级别，
    0：没有优化，
    1：进行一些基本的优化。这会使得生成的 .pyc 文件比没有优化的版本更小，并且可能运行得更快
    2：进行更多的优化。这会进一步减小 .pyc 文件的大小，并可能提高运行速度。但是，如numpy可能不可用，因为一些名称和文档字符串可能会被优化掉
    :param auto_py_pyd：知否把你的脚本目录中py转为pyd
    :param embed_exe: 是否把用户.pyc脚本嵌入exe中
    :param onefile: 是否生成只有一个exe
    :param monitoring_time: 监控工具运行时长（秒）
    :param uac: 以管理员身份运行
    :param requirements_path: 轻量模式的依赖清单文件路径
    :param except_packages: 排除的第三方包名称
    :param winres_json_path: exe应用信息文件路径
    :param delay_time: 启动监控工具后延时几秒启动用户程序
    :param all_pyc_zip: 把所有.pyc文件压缩进zip
    :param pip_source: 轻量模式pip下载源地址，默认为 https://pypi.tuna.tsinghua.edu.cn/simple
    :param kwargs: file_version: str, product_name: str, company: str
    :return:
    """

    if os.path.dirname(main_py_path) == save_dir:
        my_logger.error('save_dir不能是main_py_path所在目录')
        return

    if pack_mode not in (0, 1, 2, 3):
        my_logger.error('pack_mode参数值只限于0, 1, 2, 3')
        return

    if not os.path.exists(main_py_path):
        my_logger.error(f'未找到{main_py_path}，请检查路径')
        return

    if not save_dir:
        # 获取桌面目录
        save_dir = str(Path.joinpath(Path.home(), 'Desktop/pack_out'))
    os.makedirs(save_dir, exist_ok=True)
    if onefile:
        embed_exe = True

    if pack_mode == 2:
        embed_exe = True
        onefile = False
        if (not requirements_path) or (not os.path.exists(requirements_path)):
            my_logger.error(f'未找到依赖包文件：{requirements_path}')
            return

    rundep_dir = save_dir + '/rundep'
    if force_copy_env:
        my_logger.info('强制复制环境')
        if os.path.exists(rundep_dir):
            shutil.rmtree(rundep_dir)
        copy_py_env(save_dir, main_py_path, pack_mode, monitoring_time, except_packages, embed_exe)
    else:
        if os.path.exists(rundep_dir):
            my_logger.info('rundep文件夹已存在，跳过环境复制')
        else:
            copy_py_env(save_dir, main_py_path, pack_mode, monitoring_time, except_packages, embed_exe)

    new_main_py_path = copy_py_script(main_py_path, save_dir)

    if pack_mode == 1:
        to_slim_file(new_main_py_path, check_dir=rundep_dir, project_dir=save_dir, monitoring_time=monitoring_time,
                     pack_mode=pack_mode, delay_time=delay_time)
    elif pack_mode == 2:
        my_logger.info("复制requirements.txt")
        if requirements_path:
            save_requirements_path = Path.joinpath(Path(save_dir), 'rundep/AppData/requirements.txt')
            if save_requirements_path.exists():
                os.remove(save_requirements_path)
            shutil.copyfile(requirements_path, save_requirements_path)
        else:
            my_logger.error(f'未找到依赖包文件：{requirements_path}')
            sys.exit()

    if embed_exe:
        copy_embed_depend(save_dir, sys.base_prefix)

    # # 把用户主程序重命名为mian.py
    script_dir = save_dir + '/rundep/AppData'
    os.rename(new_main_py_path, os.path.join(script_dir, 'main.py'))

    if auto_py_pyd:
        script_dir_main_py = os.path.join(script_dir, 'main.py')
        try:
            to_pyd(script_dir, script_dir_main_py=script_dir_main_py, is_del_py=True)
        except Exception as e:
            my_logger.error(f"转pyd出错：{e}")

    if auto_py_pyc or embed_exe or onefile:
        py_to_pyc(rundep_dir, pyc_optimize)

    if not (embed_exe or onefile):
        create_bat(save_dir, embed_exe)

    build_exe(save_dir, hide_cmd, exe_name, png_path, embed_exe=embed_exe, onefile=onefile, uac=uac,
              pack_mode=pack_mode, winres_json_path=winres_json_path, all_pyc_zip=all_pyc_zip, pip_source=pip_source,
              **kwargs)

    my_logger.info('结束')
