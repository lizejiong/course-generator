import { expect, test } from "vitest";
import { stageMeta } from "./stages";
test("maps the seven backend stages", () => expect(stageMeta(7).label).toBe("确认与发布"));
