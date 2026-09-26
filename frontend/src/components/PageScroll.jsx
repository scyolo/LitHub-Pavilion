import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { parseFilters } from "../lib/presentation.js";

export default function PageScroll() {
  const { pathname, search } = useLocation();
  const filters = parseFilters(search);
  const page = pathname === "/papers" ? filters.page : 1;
  const size = pathname === "/papers" ? filters.size : 20;
  useEffect(() => { window.scrollTo({ top: 0, left: 0, behavior: "instant" }); }, [pathname, page, size]);
  return null;
}
