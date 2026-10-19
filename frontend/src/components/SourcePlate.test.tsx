// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { expect, it } from "vitest";

import { MCP_SOURCES, SEARCHED_SOURCES } from "../sources";
import { SourcePlate } from "./SourcePlate";

it("draws a leader to every source, with searched sources in the right column", () => {
  const { container } = render(<SourcePlate />);

  expect(container.querySelectorAll(".leader")).toHaveLength(MCP_SOURCES.length);
  const right = [...container.querySelectorAll(".caption-right .caption-name")].map((node) => node.textContent);
  expect(right).toEqual(SEARCHED_SOURCES.map((source) => source.name));
});
