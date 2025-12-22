"""
ast分析依赖
@author: xmqsvip
Created on 2025-01-05
"""
import copy
import logging
import os
import re
import sys
from pathlib import Path

from soeasypack.core.re_find_pkg import find_pkgs, CHECK_PKGS, EXCLUDE_DIRS
from soeasypack.lib.modulegraph2 import ModuleGraph, PyPIDistribution

logging.getLogger("comtypes").setLevel(logging.ERROR)


def add_depends(depends: set, special_pkgs: set):
    """
    补充依赖文件
    """
    add_depend_paths = []
    depend_paths_append = add_depend_paths.append
    checked_dir = set()
    has_web_engine = False
    sub_compile = re.compile(r'(?<!\\)#.*?$|(?:\'\'\'[\s\S]*?\'\'\'|\"\"\"[\s\S]*?\"\"\")', flags=re.MULTILINE)
    # # 查找可能需要的文件
    for depend_path in depends:
        if 'site-packages' not in depend_path:
            continue
        depend_path_split = depend_path.split('site-packages')
        package_name = depend_path_split[1].split('\\', 2)[1]
        package_path = depend_path_split[0] + f'site-packages\\{package_name}'
        if package_path in checked_dir or os.path.isfile(package_path):
            continue
        checked_dir.add(package_path)

        py_files_path = []
        other_files = {}
        py_files_append = py_files_path.append
        for root, dirs, files in os.walk(package_path):
            if '__pycache__' in root or ('plugins' in root and 'PySide' in root):
                continue
            for f in files:
                file_path = os.path.join(root, f)
                if f.endswith('.pyx'):
                    py_files_append(file_path)
                elif f.endswith('.py'):
                    if file_path in depends:
                        py_files_append(file_path)
                else:
                    file_name = os.path.basename(file_path)
                    if f.endswith(('.json', '.pem')):
                        add_depend_paths.append(file_path)
                        continue
                    elif f.endswith('.dll'):
                        other_files[file_name] = file_path
                    elif f.endswith('.pyd'):
                        file_name = file_name.split('.', 1)[0]
                        other_files[file_name] = file_path

        # # 判断似乎否有 QtWebEngine
        if 'PySide' in package_path:
            has_pyside = True
            if 'QtWebEngineWidgets' in depends:
                has_web_engine = True

        if not other_files:
            continue
        py_files_path.extend(other_files.values())
        for file in py_files_path:
            if file.endswith('.dll'):
                continue
            file_name = os.path.basename(file)
            mode = 'rb'
            encodings = None
            if file.endswith(('.py', 'pyx')):
                mode = 'r'
                encodings = 'utf-8'

            with open(file, mode=mode, encoding=encodings) as fp:
                content = fp.read()

            for dll_file_name in other_files:
                base_dll_name = dll_file_name.split('.', 1)[0]
                if base_dll_name.replace('Qt6', '') not in file_name:
                    is_in = False
                    if mode == 'rb':
                        dll_file_name = dll_file_name.encode('utf-8')
                        if dll_file_name.endswith(b'.dll'):
                            if dll_file_name in content:
                                is_in = True
                        else:
                            # # pyd
                            if b'.' + dll_file_name in content:
                                is_in = True
                    else:
                        # # py
                        # # 去除注释和文档字符串
                        content = sub_compile.sub('', content)
                        if dll_file_name in content or base_dll_name in content:
                            is_in = True

                    if is_in:
                        if mode == 'rb':
                            dll_file_name = dll_file_name.decode('utf-8')
                        depend_paths_append(other_files[dll_file_name])

            del content
            # # 去除WebEngine
            if not has_web_engine:
                depends_ = copy.deepcopy(add_depend_paths)
                for depend in depends_:
                    if 'Web' in depend:
                        add_depend_paths.remove(depend)
                del depends_

        # # 补充pyside/plugins文件夹内容
        if has_pyside:
            file_plugin_map = {
                "QtQuick": ["scenegraph"],
                "QtQml": ["qmltooling"],
                "QtXml": ["scxmldatamodel"],
                "QtDesigner": ["designer"],
                "QtWidgets": ["styles"],
                "QtSql": ["sqldrivers"],
                "QtSensors": ["sensors"],
                "QtDeclarative": ["qml1tooling"],
                "QtPositioning": ["position"],
                "QtLocation": ["geoservices"],
                "QtPrintSupport": ["printsupport"],
                "QtNetwork": ["networkinformation", "tls"],
                "Qt3DRender": ["geometryloaders", "renderplugins", "renderers", "sceneparsers"],
                "QtMultimedia": ["multimedia"],
                "QtGui": ["accessiblebridge", "generic", "iconengines", "imageformats",
                          "platforms", "platforminputcontexts"]
            }
            plugins_dir = os.path.join(package_path, 'plugins')
            for pyd_file in other_files:
                if not pyd_file.endswith('.dll'):
                    if pyd_file in file_plugin_map:
                        for i in file_plugin_map[pyd_file]:
                            plugin_dir = os.path.join(plugins_dir, i)
                            if os.path.exists(plugin_dir):
                                for file in os.listdir(plugin_dir):
                                    file_path = os.path.join(plugins_dir, i, file)
                                    add_depend_paths.append(file_path)


    for file_path in add_depend_paths:
        depends.add(file_path)

    current_env_dir = sys.prefix
    site_pkg_dir = os.path.join(current_env_dir, 'Lib\\site-packages')
    # 查找是否有以.pth结尾的文件
    for f in Path(site_pkg_dir).iterdir():
        if f.suffix == '.pth':
            depends.add(str(f))

    # #补充python目录下的dll
    base_env_dir = sys.base_prefix
    for f in os.listdir(base_env_dir):
        if os.path.isfile(os.path.join(base_env_dir, f)) and f.endswith('.dll'):
            dll_file = os.path.join(base_env_dir, f)
            depends.add(dll_file)

    # # 补充encodings
    # encodings_dir_files = ('gbk.py', 'latin_1.py', 'utf_8.py', 'utf_16_be.py', 'cp437.py')
    # for encodings_file in encodings_dir_files:
    #     depends.add(os.path.join(base_env_dir, 'Lib', 'encodings', encodings_file))
    encodings_path = os.path.join(base_env_dir, 'Lib', 'encodings')
    for f in os.listdir(encodings_path):
        if f.endswith('.py'):
            depends.add(os.path.join(encodings_path, f))

    # # 补充libxxx.dll
    dlls_dir = os.path.join(base_env_dir, 'DLLs')
    for f in os.listdir(dlls_dir):
        file_path = os.path.join(dlls_dir, f)
        if 'lib' in f and os.path.isfile(file_path):
            dll_file_path = file_path
            depends.add(dll_file_path)

    # #补充tkinter包数据
    dlls_dir_files = []
    if 'tkinter' in special_pkgs:
        import tkinter
        import _tkinter
        tcl_version, tk_version = _tkinter.TCL_VERSION, _tkinter.TK_VERSION
        tcl_v = tcl_version.replace('.', '')
        tk_v = tk_version.replace('.', '')
        tcl = tkinter.Tcl()
        tcl_dir = tcl.eval("info library")
        tk_dir = f"{os.path.dirname(tcl_dir)}\\tk{tk_version}"
        dlls_dir_files.extend([f'tcl{tcl_v}t.dll', f'tk{tk_v}t.dll'])
        for root, _, files in os.walk(tcl_dir, topdown=True):
            for f in files:
                depends.add(os.path.join(root, f))
        for root, _, files in os.walk(tk_dir, topdown=True):
            if 'demos' in root or '__pycache__' in root:
                continue
            for f in files:
                depends.add(os.path.join(root, f))

    for dlls_file in dlls_dir_files:
        depends.add(os.path.join(dlls_dir, dlls_file))

    # #补充curl_cffi包数据
    if 'curl_cffi' in special_pkgs:
        for dir_ in os.listdir(site_pkg_dir):
            if 'curl_cffi' in dir_ and (not dir_.endswith('curl_cffi')):
                full_dir = os.path.join(site_pkg_dir, dir_)
                for root, dirs, files in os.walk(full_dir):
                    for f in files:
                        depends.add(os.path.join(root, f))
    # # 补充pywebview
    if 'webview' in special_pkgs:
        for root, dirs, files in os.walk(f"{site_pkg_dir}/webview/lib/runtimes"):
            for file in files:
                file_path = os.path.join(root, file)
                depends.add(file_path)


def analyze_depends(main_script_path: str, except_pkgs: list = None):
    """
    分析给定Python项目主文件的所有依赖关系。
    """

    base_env_dir = sys.base_prefix
    current_env_dir = sys.prefix
    sys_path = sys.path
    script_dir = os.path.dirname(os.path.abspath(main_script_path))
    search_paths = [script_dir]
    for path in sys_path:
        if base_env_dir in path or current_env_dir in path:
            search_paths.append(path)

    sys.path = search_paths

    excludes = ['IPython', 'test', 'tests', 'pip', 'lib2to3', 'pydoc_data', 'pkg_resources',
                'pycparser', 'packaging', 'setuptools', 'unittest'] + EXCLUDE_DIRS

    project_pkg_names = find_pkgs(main_script_path)

    for check_pkg in CHECK_PKGS:
        if check_pkg not in project_pkg_names:
            excludes.append(check_pkg)

    if except_pkgs:
        excludes.extend(except_pkgs)

    mg = ModuleGraph()
    mg.add_excludes(excludes)

    depends = set()
    special_pkgs = set()
    mg.add_script(main_script_path)

    for node in mg.iter_graph():
        if isinstance(node, PyPIDistribution):
            continue
        if node.filename:
            file_path = os.path.abspath(node.filename)
            if base_env_dir in file_path or current_env_dir in file_path:
                if type(node).__name__ == "Package":
                    file_path = os.path.join(file_path, '__init__.py')
                if 'tkinter' in file_path:
                    special_pkgs.add('tkinter')
                elif 'curl_cffi' in file_path:
                    special_pkgs.add('curl_cffi')
                elif 'webview' in file_path:
                    special_pkgs.add('webview')

                depends.add(file_path)

    add_depends(depends, special_pkgs)
    return depends