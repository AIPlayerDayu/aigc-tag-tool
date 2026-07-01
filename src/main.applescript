-- AI 元数据检测器 (AppleScript applet)
-- 打开 App：启动本地服务并打开拖拽网页。
-- 拖文件到 App 图标：把这些本地路径直接送去检测。

on run
	launchAndOpen({})
end run

on open theItems
	set paths to {}
	repeat with f in theItems
		set end of paths to POSIX path of (f as alias)
	end repeat
	launchAndOpen(paths)
end open

on launchAndOpen(posixPaths)
	set appPath to POSIX path of (path to me)
	set server to appPath & "Contents/Resources/server.py"
	set pythonPath to "/usr/bin/python3"
	repeat with c in {"/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"}
		try
			do shell script "/usr/bin/test -x " & quoted form of (c as text)
			set pythonPath to (c as text)
			exit repeat
		end try
	end repeat

	-- 让 detect.py 能找到 exiftool / ffmpeg（GUI 启动时 PATH 很精简）
	set pathEnv to "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin export PATH; "
	-- 后台启动服务（若端口已被占用会自行退出，等于复用已有实例）
	do shell script pathEnv & quoted form of pythonPath & " " & quoted form of server & " >/dev/null 2>&1 &"

	-- 等待服务就绪
	repeat 40 times
		try
			do shell script "/usr/bin/curl -s http://127.0.0.1:8765/ping"
			exit repeat
		end try
		delay 0.1
	end repeat

	set theURL to "http://127.0.0.1:8765/"
	if (count of posixPaths) > 0 then
		set jsonArr to "["
		repeat with i from 1 to count of posixPaths
			set p to item i of posixPaths
			if i > 1 then set jsonArr to jsonArr & ","
			set jsonArr to jsonArr & "\"" & my urlEncode(p) & "\""
		end repeat
		set jsonArr to jsonArr & "]"
		set theURL to theURL & "?paths=" & my urlEncode(jsonArr)
	end if
	do shell script "/usr/bin/open " & quoted form of theURL
end launchAndOpen

-- 用 python 做 URL 编码，稳妥处理中文/空格路径
on urlEncode(s)
	set py to "/usr/bin/python3"
	return do shell script py & " -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=\"\"))' " & quoted form of s
end urlEncode
