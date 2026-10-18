import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./index.css";
import { Layout } from "@/components/Layout";
import { TooltipProvider } from "@/components/ui/tooltip";
import { I18nProvider } from "@/i18n";
import { UploadPage } from "@/pages/UploadPage";
import { ProcessingPage } from "@/pages/ProcessingPage";
import { ReviewPage } from "@/pages/ReviewPage";
import { ExportPage } from "@/pages/ExportPage";
import { AuthProvider, RequireAuth } from "@/auth/AuthProvider";
import { LoginPage } from "@/pages/LoginPage";
import { MePage } from "@/pages/MePage";
import { DashboardPage } from "@/pages/DashboardPage";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    // everything else needs a logged-in user; some screens only certain roles
    element: <RequireAuth />,
    children: [
      {
        element: <Layout />,
        children: [
          {
            path: "/",
            element: <RequireAuth roles={["intake", "lab_manager"]} />,
            children: [{ index: true, element: <UploadPage /> }],
          },
          { path: "/me", element: <MePage /> },
          {
            path: "/dashboard",
            element: <RequireAuth roles={["lab_manager"]} />,
            children: [{ index: true, element: <DashboardPage /> }],
          },
          {
            path: "/batches/:id",
            children: [
              { index: true, element: <ReviewPage /> },
              { path: "processing", element: <ProcessingPage /> },
              {
                path: "export",
                element: <RequireAuth roles={["lab_manager"]} />,
                children: [{ index: true, element: <ExportPage /> }],
              },
            ],
          },
        ],
      },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <TooltipProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </TooltipProvider>
    </I18nProvider>
  </React.StrictMode>,
);
