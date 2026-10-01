# 测试素材

## kara_t1.ass

**本仓库作者自己写的**卡拉OK模板（不是社区模板，可以随仓库分发）：5 条 template/code 行，
故意同时用上 syl 级和 char 级模板行（提交给模板表达式的变量不一样），外加一条自制歌词行——
真实用法里 `template_rows()` 会把非注释行过滤掉。

用来验证：真模板喂进卡拉OK页，能不能跑通模板引擎、`\k` 切法保不保得住、fx 行跟不跟源行。
`test_roundtrip.py` 和 `test_gui.py` 都用它；也可以用 `ZX_KARA_TEMPLATE` 指别的模板文件。

社区模板不随仓库分发：插件按需从 GitHub 下载到用户本机（版权归各原作者），见 NOTICE。

## generated/

测试运行时自己生成的素材（合成字幕、工作台导出、GUI 截图、合成视频），已经在 .gitignore 里，不入库。
