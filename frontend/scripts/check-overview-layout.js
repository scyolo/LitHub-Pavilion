// Run against a populated preview with playwright-cli run-code --filename=frontend/scripts/check-overview-layout.js.
// Real-browser geometry checks cover the grid-stretch regression that jsdom cannot detect.
async page => {
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const home = new URL(page.url());
  home.hash = "/";
  const errors = [];
  const onError = error => errors.push(error.message);
  page.on("pageerror", onError);
  try {
    await page.goto(home.href);
    await page.getByRole("heading", { name: "年度收录分布", exact: true }).waitFor();
    const layouts = [];
    for (const theme of ["light", "dark"]) {
      const themeButton = page.getByRole("button", { name: theme === "light" ? "切换浅色主题" : "切换深色主题", exact: true });
      if (await themeButton.count()) await themeButton.click();
      for (const width of [1920, 1600, 1440, 1280, 1024, 980, 760, 390, 320]) {
        await page.setViewportSize({ width, height: 1000 });
        const layout = await page.evaluate(() => {
          const annual = document.querySelector(".annual-panel");
          const topics = document.querySelector(".topic-panel");
          const list = topics.querySelector(".topic-bars");
          const footnote = annual.querySelector(".chart-footnote");
          const annualBox = annual.getBoundingClientRect();
          const topicsBox = topics.getBoundingClientRect();
          const chartsBox = annual.parentElement.getBoundingClientRect();
          return {
            width: innerWidth, theme: document.documentElement.dataset.theme,
            annualHeight: annualBox.height, topicsHeight: topicsBox.height,
            trailingSpace: annualBox.bottom - footnote.getBoundingClientRect().bottom,
            unusedRowSpace: chartsBox.bottom - annualBox.bottom,
            sameRow: Math.abs(annualBox.top - topicsBox.top) < 1,
            topicViewport: list.clientHeight, topicContent: list.scrollHeight,
            topicCount: list.querySelectorAll("button").length,
            allDirectionCount: document.querySelectorAll(".topic-tiles > button").length,
            overflow: document.documentElement.scrollWidth > innerWidth,
          };
        });
        check(layout.trailingSpace <= 24, `Annual chart has ${layout.trailingSpace}px of unused space at ${width}px (${theme})`);
        check(!layout.overflow, `Horizontal overflow at ${width}px (${theme})`);
        check(layout.annualHeight < 420 && layout.topicsHeight < 450, `Summary panels should stay compact at ${width}px (${theme})`);
        check(layout.topicViewport <= 232, `Topic list must be bounded at ${width}px (${theme})`);
        check(layout.topicCount === layout.allDirectionCount, "The compact list must retain every direction");
        if (layout.sameRow) check(layout.unusedRowSpace <= 90, "Whitespace must not simply move outside the annual card");
        layouts.push(layout);
      }
    }
    check(await page.getByRole("region", { name: "CCF 顶会与顶刊", exact: true }).count() === 0, "The venue directory must not appear on the overview");
    check(await page.getByRole("searchbox", { name: "搜索会议期刊", exact: true }).count() === 0, "The overview must not duplicate the venue search");
    await page.setViewportSize({ width: 1440, height: 1000 });
    const list = page.getByRole("region", { name: "研究主题列表", exact: true });
    check(await list.getAttribute("tabindex") === "0", "The topic list needs keyboard scrolling access");
    if (await list.getByRole("button").count()) {
      await list.focus();
      await page.keyboard.press("End");
      await page.waitForFunction(() => {
        const list = document.querySelector(".topic-bars");
        return list.scrollHeight <= list.clientHeight || list.scrollTop > 0;
      });
      const last = list.getByRole("button").last();
      await last.focus();
      const visible = await last.evaluate(button => {
        const box = button.getBoundingClientRect();
        const container = button.closest(".topic-bars").getBoundingClientRect();
        return box.top >= container.top && box.bottom <= container.bottom + 1;
      });
      check(visible, "The final direction must be reachable without clipping");
    }
    check(!errors.length, `Browser errors: ${errors.join("; ")}`);
    return { verified: true, layouts, overviewDirectoryRemoved: true, allTopicsRetained: true, keyboardScroll: true, errors };
  } finally {
    page.off("pageerror", onError);
  }
}
