import { act, render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import PageScroll from "./PageScroll.jsx";

function Navigation() {
  const navigate = useNavigate();
  return <><PageScroll /><button onClick={() => navigate("/papers?page=2&size=10")}>Next</button><button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate("/papers?size=50")}>Size</button><button onClick={() => navigate("/papers?q=agent&size=10")}>Query</button></>;
}
beforeEach(() => vi.mocked(window.scrollTo).mockClear());
it("scrolls instantly for page and page-size navigation, including browser history", () => {
  render(<MemoryRouter initialEntries={["/papers?size=10"]}><Navigation /></MemoryRouter>);
  vi.mocked(window.scrollTo).mockClear();
  fireEvent.click(screen.getByText("Next"));
  expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 0, left: 0, behavior: "instant" });
  fireEvent.click(screen.getByText("Back"));
  expect(window.scrollTo).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByText("Size"));
  expect(window.scrollTo).toHaveBeenCalledTimes(3);
});
it("does not reset scroll on unrelated state or same-page query edits", () => {
  const view = render(<MemoryRouter initialEntries={["/papers?size=10"]}><Navigation /></MemoryRouter>);
  vi.mocked(window.scrollTo).mockClear();
  fireEvent.click(screen.getByText("Query"));
  act(() => view.rerender(<MemoryRouter initialEntries={["/papers?size=10"]}><Navigation /></MemoryRouter>));
  expect(window.scrollTo).not.toHaveBeenCalled();
});
