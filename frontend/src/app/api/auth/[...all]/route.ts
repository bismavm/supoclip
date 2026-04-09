import { auth } from "@/lib/auth";
import { toNextJsHandler } from "better-auth/next-js";

const authRouteHandler = toNextJsHandler(auth.handler);

export async function GET(request: Request) {
  return authRouteHandler.GET(request);
}

export async function POST(request: Request) {
  return authRouteHandler.POST(request);
}
