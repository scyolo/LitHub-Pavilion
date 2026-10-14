import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import MythicHero from "./MythicHero.jsx";

const wrap = (props = {}) => <MemoryRouter><MythicHero {...props} /></MemoryRouter>;
const mount = (props) => render(wrap(props));
afterEach(() => vi.unstubAllGlobals());

describe("the two celestial realms", () => {
  it("renders an atmospheric white-gold cloud sea for the light theme", () => {
    const { container } = mount({ theme: "light" });
    expect(screen.getByRole("heading", { level: 1, name: /海纳百川/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /海纳百川/ })).toHaveAttribute("data-realm", "heaven");
    expect(container.querySelector('[data-scene="hongmeng-cloud-sea"]')).toBeInTheDocument();
    expect(container.querySelector('[data-scene="zhou-tian-stars"]')).not.toBeInTheDocument();
    expect(screen.getByText("鸿蒙云海")).toBeInTheDocument();
  });
  it("renders a different star-map scene for dark mode and preserves a manual pause", () => {
    const { container, rerender } = mount({ theme: "light" });
    fireEvent.click(screen.getByRole("button", { name: "暂停封面动画" }));
    rerender(wrap({ theme: "dark" }));
    expect(container.querySelector('[data-scene="zhou-tian-stars"]')).toBeInTheDocument();
    expect(container.querySelector('[data-scene="hongmeng-cloud-sea"]')).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: /海纳百川/ })).toHaveAttribute("data-motion", "paused");
    expect(screen.getByText("周天星空")).toBeInTheDocument();
    expect(container.querySelectorAll('svg[data-scene]')).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "播放封面动画" }));
    expect(screen.getByRole("region", { name: /海纳百川/ })).toHaveAttribute("data-motion", "running");
  });
  it("offers real exploration links and requests whole-site theme changes", () => {
    const onThemeChange = vi.fn();
    mount({ theme: "dark", onThemeChange });
    expect(screen.getByRole("link", { name: /探索论文/ })).toHaveAttribute("href", "/papers");
    expect(screen.getByRole("link", { name: /浏览来源/ })).toHaveAttribute("href", "/venues");
    fireEvent.click(screen.getByRole("button", { name: "切换至鸿蒙云海" }));
    expect(onThemeChange).toHaveBeenCalledWith("light");
    expect(screen.getByRole("button", { name: "切换至周天星空" })).toHaveAttribute("aria-pressed", "true");
  });
  it("respects reduced motion before interaction and keeps a manual pause on preference changes", () => {
    let change;
    const remove = vi.fn();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: (_, handler) => { change = handler; }, removeEventListener: remove })));
    const { unmount } = mount({ theme: "light" });
    expect(screen.getByRole("region", { name: /海纳百川/ })).toHaveAttribute("data-motion", "paused");
    expect(screen.getByRole("button", { name: "系统已减少动态效果" })).toBeDisabled();
    act(() => change({ matches: false }));
    fireEvent.click(screen.getByRole("button", { name: "暂停封面动画" }));
    act(() => change({ matches: true }));
    act(() => change({ matches: false }));
    expect(screen.getByRole("region", { name: /海纳百川/ })).toHaveAttribute("data-motion", "paused");
    unmount();
    expect(remove).toHaveBeenCalledWith("change", change);
  });
});


describe("the boundless white-gold realm", () => {
  it("evokes a boundless confluence without any palace, gate or staircase", () => {
    const { container } = mount({ theme: "light" });
    const scene = container.querySelector('[data-scene="hongmeng-cloud-sea"]');
    expect(scene).toHaveAttribute("data-composition", "boundless-confluence");
    expect(scene.querySelector('canvas[data-layer="atmosphere"]')).toBeInTheDocument();
    expect(container.querySelector('[data-layer="imperial-gate"], [data-layer="jade-causeway"], .court-art')).not.toBeInTheDocument();
    expect(screen.queryByText("南天门")).not.toBeInTheDocument();
    expect(screen.getByText("鸿 蒙 云 海")).toBeInTheDocument();
    expect(scene).toHaveAttribute("aria-hidden", "true");
    expect(scene).toHaveAttribute("data-paused", "false");
    fireEvent.click(screen.getByRole("button", { name: "暂停封面动画" }));
    expect(scene).toHaveAttribute("data-paused", "true");
  });

  it("keeps any decorative references local when more than one cloud sea is rendered", () => {
    const { container } = render(<MemoryRouter><MythicHero theme="light" /><MythicHero theme="light" /></MemoryRouter>);
    const ids = [...container.querySelectorAll("[id]")].map(element => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const scene of container.querySelectorAll('[data-scene="hongmeng-cloud-sea"]')) {
      const localIds = new Set([...scene.querySelectorAll("[id]")].map(element => element.id));
      for (const element of scene.querySelectorAll("*")) {
        for (const attribute of element.attributes) {
          const references = attribute.value.matchAll(/url\(#([^)]*)\)|^#(celestial-[^ ]+)$/g);
          for (const match of references) expect(localIds.has(match[1] || match[2])).toBe(true);
        }
      }
    }
  });
});
