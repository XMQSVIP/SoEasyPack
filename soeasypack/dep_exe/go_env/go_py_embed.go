/*
 * @Author: xmqsvip
 * @Date: 2024-12-15
 * @go version:1.23.4

 */

package main

import (
	"archive/zip"
	"bytes"
	"embed"
	"fmt"
	"io"
	"os"
	"os/exec"
	"math/rand"
	"path/filepath"
	"runtime"
	"sync"
	"unsafe"
	"windows"
)

//go:embed soeasypack.sz
var embedZip embed.FS
var onefile bool = false
var packmode int = 0
var mainPyCode string = `main_pycode`
var memoryName string = "memory_name"
var xorKey string = "xor_key"
func MessageBox(title, message string) {
	user32, _ := windows.LoadDLL("user32.dll")

	defer user32.Release()

	proc := user32.MustFindProc("MessageBoxW")

	titlePtr, _ := windows.UTF16PtrFromString(title)

	messagePtr, _ := windows.UTF16PtrFromString(message)

	proc.Call(0, uintptr(unsafe.Pointer(messagePtr)), uintptr(unsafe.Pointer(titlePtr)), 0x10)
}

func fileExists(filename string) bool {
	_, err := os.Stat(filename)
	if err != nil {
		if os.IsNotExist(err) {
			return false
		}
		return false
	}
	return true
}
func generateRandomString(length int) (string, error) {
	const letterBytes = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	b := make([]byte, length)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}

	for i := range b {
		b[i] = letterBytes[b[i]%byte(len(letterBytes))]
	}
	return string(b), nil
}
func createSharedMemory() (windows.Handle, uintptr) {
	zipData, err := embedZip.ReadFile("soeasypack.sz")
	if err != nil {
		MessageBox("错误", "找不到zipData:"+err.Error())
		return 0, 0
	}

	memSize := len(zipData)
	memoryName, _ := generateRandomString(8)
	os.Setenv("MEMORY_NAME", memoryName)

	securityAttrs := &windows.SecurityAttributes{
		Length:        uint32(unsafe.Sizeof(windows.SecurityAttributes{})),
		InheritHandle: 1,
	}

	namePtr, err := windows.UTF16PtrFromString(memoryName)
	if err != nil {
		MessageBox("错误", "UTF16PtrFromString 错误: "+err.Error())
		return 0, 0
	}

	handle, err := windows.CreateFileMapping(windows.InvalidHandle, securityAttrs, windows.PAGE_READWRITE, 0, uint32(memSize), namePtr)
	if err != nil {
		MessageBox("错误", "创建共享内存失败:"+err.Error())
		return 0, 0
	}

	addr, err := windows.MapViewOfFile(handle, windows.FILE_MAP_WRITE, 0, 0, uintptr(memSize))
	if err != nil {
		windows.CloseHandle(handle)
		MessageBox("错误", "映射共享内存到当前进程的地址空间失败:"+err.Error())
		return 0, 0
	}

	copy((*[1 << 30]byte)(unsafe.Pointer(addr))[:memSize], zipData)
	return handle, addr
}

var bufferPool = sync.Pool{
	New: func() interface{} {
		return make([]byte, 32*1024) // 默认缓冲区大小 32KB
	},
}

func processFile(f *zip.File, dest string) error {
	fpath := filepath.Join(dest, f.Name)
	if f.FileInfo().IsDir() {
		return os.MkdirAll(fpath, os.ModePerm)
	}
	if err := os.MkdirAll(filepath.Dir(fpath), os.ModePerm); err != nil {
		return err
	}

	outFile, err := os.OpenFile(fpath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, f.Mode())
	if err != nil {
		return err
	}
	defer outFile.Close()

	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()

	buffer := bufferPool.Get().([]byte)
	defer bufferPool.Put(buffer)

	_, err = io.CopyBuffer(outFile, rc, buffer)
	return err
}

func extractZip(zipReader io.ReaderAt, size int64, dest string) error {
	zipR, err := zip.NewReader(zipReader, size)
	if err != nil {
		return err
	}

	maxConcurrency := runtime.NumCPU()
	sem := make(chan struct{}, maxConcurrency)

	var wg sync.WaitGroup
	var mu sync.Mutex
	var firstErr error

	for _, f := range zipR.File {
		wg.Add(1)
		sem <- struct{}{} // 控制并发
		go func(file *zip.File) {
			defer wg.Done()
			defer func() { <-sem }()

			if err := processFile(file, dest); err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mu.Unlock()
			}
		}(f)
	}

	wg.Wait()
	return firstErr
}

type stderrCapturer struct {
	buf *bytes.Buffer
}

// 实现 io.Writer 的 Write 方法
func (c *stderrCapturer) Write(p []byte) (n int, err error) {
	return c.buf.Write(p)
}
func main() {
	var pyDllPath string
	SEPHOME := os.Getenv("SEPHOME")
	if SEPHOME == "" {
		originDir, _ := os.Getwd()
		os.Setenv("originDir", originDir)
		if onefile {
			// 创建临时目录
			var err error
			currentDir, err := os.MkdirTemp("", "soeasypack")
			if err != nil {
				return
			}
			// 读取嵌入的zip文件内容
			zipData, err := embedZip.ReadFile("rundep.zip")
			if err != nil {
				MessageBox("错误", "读取压缩包数据失败: "+err.Error())
				return
			}

			// 使用bytes.Reader包装zip数据，以提供io.ReaderAt接口
			zipReader := bytes.NewReader(zipData)
			rundepDir := currentDir + "\\rundep"
			// 解压zip文件到临时目录
			if err := extractZip(zipReader, int64(len(zipData)), rundepDir); err != nil {
				MessageBox("错误", "解压数据到临时目录失败: "+err.Error())
				return
			}
			SEPHOME = currentDir
			os.Setenv("SEPHOME", currentDir)
			os.Setenv("PYTHONHOME", SEPHOME+"\\rundep")
			// os.Setenv("ONEFILE", "1")
			pyDllPath = SEPHOME + "\\rundep\\python3.dll"
			os.Setenv("pyDllPath", pyDllPath)
			handle, addr := createSharedMemory()
			if handle == 0 {
			    MessageBox("异常", "程序将退出")
				os.RemoveAll(currentDir) // 创建共享内存失败，删除临时目录
				return
			}
			defer windows.CloseHandle(handle)
			defer windows.UnmapViewOfFile(addr)
			executable, _ := os.Executable()
			cmd := exec.Command(executable)
			cmd.Stdout = os.Stdout
			cmd.Stderr = os.Stderr
			if err := cmd.Run(); err != nil {
				MessageBox("错误", "启动失败: "+err.Error())
			}
			os.RemoveAll(currentDir) // 程序退出时删除临时目录
			return
		} else {
			currentDir, _ := os.Getwd()
			SEPHOME = currentDir
			os.Setenv("SEPHOME", currentDir)
			os.Setenv("PYTHONHOME", SEPHOME+"\\rundep")
			pyDllPath = SEPHOME + "\\rundep\\python3.dll"
			os.Chdir(SEPHOME + "\\rundep")
			// 轻量打包模式
			if packmode == 2 {
				isExist := fileExists("compiled_pip.txt")
				if !isExist {
					MessageBox("提示", "依赖包不全，将准备自动下载依赖包")
					cmd := exec.Command("cmd", "/c", "python.exe -m ensurepip --upgrade")

					cmd.Stdout = os.Stdout
					cmd.Stderr = os.Stderr
					err := cmd.Run()
					if err != nil {
						MessageBox("提示", "自动下载依赖包失败:"+err.Error())
						os.Exit(1)
					} else {
					    cmd := exec.Command("cmd", "/c", "python.exe -m pip install -U pip -i pip_source")
						cmd.Stdout = os.Stdout
						cmd.Stderr = os.Stderr
						cmd.Run()
						cmd = exec.Command("cmd", "/c", "python.exe -m pip install -r AppData\\requirements.txt -i pip_source")
						cmd.Stdout = os.Stdout
						cmd.Stderr = os.Stderr

						err := cmd.Run()
						if err != nil {
							MessageBox("提示", "安装依赖包失败:"+err.Error())
							os.Exit(1)
						} else {
							f, _ := os.Create("compiled_pip.txt")
							f.Close()
						}
					}

				}

			}
			os.Setenv("pyDllPath", pyDllPath)
			handle, addr := createSharedMemory()
			defer windows.CloseHandle(handle)
			defer windows.UnmapViewOfFile(addr)
		}

	} else {
	    memName := os.Getenv("MEMORY_NAME")
        if memName != "" {
            memoryName = memName
        }
		pyDllPath = os.Getenv("pyDllPath")
		os.Setenv("isSubProcess", "1")
	}

	pyCode := fmt.Sprintf(`
import os
import sys
import marshal
import zipfile
import importlib.abc
import importlib.util
from io import BytesIO, BufferedReader
from multiprocessing import shared_memory as shm
from importlib.machinery import ExtensionFileLoader, EXTENSION_SUFFIXES, FileFinder

class ZipMemoryLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, zip_data):
        self.zip_data = zip_data
        self.zip_file = zipfile.ZipFile(BytesIO(zip_data), 'r')
        self.module_cache = {}  # 缓存模块路径到模块名的映射
        self.rundep_dir = os.path.dirname(os.getcwd())
        # 构建模块路径缓存
        for path in self.zip_file.namelist():
            # 将路径转换为模块名
            module_name = path[:-4].replace('/', '.').replace('\\', '.')
            if module_name.endswith('.__init__'):
                module_name = module_name[:-9]  # 去掉包的 .__init__
            self.module_cache[module_name] = path

    def find_spec(self, fullname, path, target=None):
        """
        查找模块规格，支持加载单模块和嵌套包。
        """

        origin = self.module_cache.get(fullname)
        if origin:
            is_package = origin.endswith('/__init__.pyc')
            spec = importlib.util.spec_from_loader(fullname, self, origin=origin)
            if is_package:
                spec.submodule_search_locations = [origin[:-13]]  # 去掉 /__init__.pyc
            return spec

        loader_details = (ExtensionFileLoader, EXTENSION_SUFFIXES)
        search_paths = [f"{self.rundep_dir}/Lib/site-packages/", f"{self.rundep_dir}/AppData/"]
        for search_path in search_paths:
            base_pkg_name = fullname.rsplit('.', 1)[0].replace('.', '/')
            file_finder = FileFinder(search_path + base_pkg_name, loader_details)
            spec = file_finder.find_spec(fullname)
            if spec and spec.loader:
                return spec

        return None

    def create_module(self, spec):
        """
        使用默认行为创建模块。
        """
        return None

    def exec_module(self, module):
        """
        执行模块代码，将其加载到模块的命名空间中。
        """
        spec = module.__spec__
        origin = spec.origin
        if origin and origin in self.zip_file.namelist():
            with self.zip_file.open(origin) as source_file:
                # 跳过 pyc 文件头部并加载字节码
                source_file.read(16)  # 跳过 16 字节头部
                code = marshal.load(source_file)
                # 如果是包，设置 __package__ 和 __path__
                if spec.submodule_search_locations:
                    module.__package__ = spec.name
                    module.__path__ = spec.submodule_search_locations
                else:
                    module.__package__ = spec.parent

                # 执行模块代码
                exec(code, module.__dict__)

shared_mem = shm.SharedMemory(name="%s")
zip_data = bytearray(shared_mem.buf.tobytes())
shared_mem.close()
del shared_mem
key_bytes = "%s".encode('utf-8')
key_length = len(key_bytes)
len_data = len(zip_data)
for i in range(len_data):
    zip_data[i] ^= key_bytes[i %% key_length]
zip_data = bytes(zip_data)
loader = ZipMemoryLoader(zip_data)
sys.meta_path.insert(0, loader)
sys.frozen = True
globals_ = {'__file__': 'main', '__name__': '__main__'}
#globals_ = globals().update(globals_)
# 将十六进制字符串转换回字节序列
pyc_data = bytes.fromhex("%s")
compiled_code = marshal.loads(pyc_data[16:])
sys.path = [i for i in sys.path if 'rundep' in i]
try:
    exec(compiled_code, globals_)
except Exception:
    import ctypes
    import traceback
    e = traceback.format_exc()
    print(e)
    ctypes.windll.user32.MessageBoxW(0, e, "错误", 0x10)
`, memoryName, xorKey, mainPyCode)

	// 切换工作目录
	os.Chdir(SEPHOME + "\\rundep\\AppData")
	// 加载 pythonxx.dll
	pythonDll, err := windows.LoadDLL(pyDllPath)
	if err != nil {
		MessageBox("错误", "无法加载 python3.dll: "+err.Error())
		return
	}
	defer pythonDll.Release()

	// 获取 Py_Main 函数的地址
	pyMainProc, err := pythonDll.FindProc("Py_Main")
	if err != nil {
		MessageBox("错误", "无法找到 Py_Main 函数: "+err.Error())
		return
	}

	args := []string{"python", "-c", pyCode}
	args = append(args, os.Args[1:]...)

	// 将命令行参数转换为 C 字符串
	var cArgs []uintptr
	for _, arg := range args {
		arg_, _ := windows.UTF16PtrFromString(arg)
		cArgs = append(cArgs, uintptr(unsafe.Pointer(arg_)))
	}

	// 调用 Py_Main 函数执行 Python 脚本
	argc := len(args)
	argv := uintptr(unsafe.Pointer(&cArgs[0]))
	ret, _, _ := pyMainProc.Call(uintptr(argc), argv)
	if ret != 0 {
		MessageBox("错误", "执行失败,设置hide_cmd为False重新编译然后控制台运行\n或设置auto_py_pyc=False, embed_exe=True，然后cmd 运行 run.bat 查看报错信息")
	}
	// 确保 Python 环境被正确清理
	finalize, _ := pythonDll.FindProc("Py_FinalizeEx")
	finalize.Call()
	originDir := os.Getenv("originDir")
	os.Chdir(originDir)
	pythonDll.Release()

	kernel32 := windows.NewLazySystemDLL("kernel32.dll")
	procFreeLibrary := kernel32.NewProc("FreeLibrary")
	procFreeLibrary.Call(uintptr(pythonDll.Handle))
}
