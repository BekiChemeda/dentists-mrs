import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { initTheme } from "./lib/theme";
import { startTableLabels } from "./lib/tableLabels";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import "./i18n";
import "./styles.css";
import { ApiError } from "./api/client";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { RequireAuth, RequirePermission } from "./auth/guards";
import { AppShell } from "./layout/AppShell";
import { NAV_ITEMS } from "./navigation";
import { ChangePasswordPage, LoginPage } from "./pages/auth";
import { DashboardPage } from "./pages/dashboard";
import { lazyPage } from "./lazy";

// Each area of the application loads when it is first opened, so the first page appears sooner on
// slow clinic computers. The sign-in page and the home page are part of the first download.
const AuditPage = lazyPage(() => import("./pages/audit"), "AuditPage");
const ClinicSettingsPage = lazyPage(() => import("./pages/clinic-settings"), "ClinicSettingsPage");
const RolesPage = lazyPage(() => import("./pages/roles"), "RolesPage");
const UsersPage = lazyPage(() => import("./pages/admin"), "UsersPage");
const CalendarPage = lazyPage(() => import("./pages/calendar"), "CalendarPage");
const AppointmentsPage = lazyPage(() => import("./pages/appointments"), "AppointmentsPage");
const ApprovalsPage = lazyPage(() => import("./pages/approvals"), "ApprovalsPage");
const BillingPage = lazyPage(() => import("./pages/billing"), "BillingPage");
const InvoicePage = lazyPage(() => import("./pages/billing"), "InvoicePage");
const CataloguePage = lazyPage(() => import("./pages/catalogue"), "CataloguePage");
const ConsultationWorkspace = lazyPage(() => import("./pages/consultation"), "ConsultationWorkspace");
const ConsultationsPage = lazyPage(() => import("./pages/consultation"), "ConsultationsPage");
const InventoryPage = lazyPage(() => import("./pages/inventory"), "InventoryPage");
const LaboratoryPage = lazyPage(() => import("./pages/laboratory"), "LaboratoryPage");
const PatientChart = lazyPage(() => import("./pages/patients"), "PatientChart");
const PatientsPage = lazyPage(() => import("./pages/patients"), "PatientsPage");
const PharmacyPage = lazyPage(() => import("./pages/pharmacy"), "PharmacyPage");
const QueuePage = lazyPage(() => import("./pages/queue"), "QueuePage");
const TriagePage = lazyPage(() => import("./pages/queue"), "TriagePage");
const ReportsPage = lazyPage(() => import("./pages/reports"), "ReportsPage");
const AccountSecurityPage = lazyPage(() => import("./pages/security"), "AccountSecurityPage");
const AnnouncementsPage = lazyPage(() => import("./pages/announcements"), "AnnouncementsPage");
const PhonesPage = lazyPage(() => import("./pages/phones"), "PhonesPage");
const DepartmentsPage = lazyPage(() => import("./pages/departments"), "DepartmentsPage");
const SystemPage = lazyPage(() => import("./pages/system"), "SystemPage");
const DentalWorkspace = lazyPage(() => import("./pages/dental/Workspace"), "DentalWorkspace");
const DentalPatientPage = lazyPage(() => import("./pages/dental/Pages"), "DentalPatientPage");
const DentalEncountersPage = lazyPage(() => import("./pages/dental/Pages"), "DentalEncountersPage");
const RecallsPage = lazyPage(() => import("./pages/dental/Pages"), "RecallsPage");
const LabCasesPage = lazyPage(() => import("./pages/dental/Pages"), "LabCasesPage");
const DentalCataloguePage = lazyPage(() => import("./pages/dental/Pages"), "DentalCataloguePage");
const OrthoCasesPage = lazyPage(() => import("./pages/dental/Ortho"), "OrthoCasesPage");

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
});

function NotFound() {
  const { t } = useTranslation();
  return (
    <section className="panel" style={{ padding: 24 }}>
      <h1>{t("common.not_found")}</h1>
      <Link to="/">{t("common.back_home")}</Link>
    </section>
  );
}

/** Guard a route with the same permissions its navigation item uses. */
function Guarded({ nav, children }: { nav: string; children: ReactNode }) {
  const item = NAV_ITEMS.find((i) => i.key === nav);
  const { moduleOn } = useAuth();
  const { t } = useTranslation();
  if (item?.module && !moduleOn(item.module)) {
    return (
      <section className="panel" style={{ padding: 24 }}>
        <h1>{t("modules.page_off_title", "This part of the system is switched off")}</h1>
        <p className="muted">
          {t("modules.page_off_body", "The system administrator has switched this module off for the clinic.")}
        </p>
        <Link to="/">{t("common.back_home")}</Link>
      </section>
    );
  }
  return <RequirePermission anyOf={item?.anyOf ?? []}>{children}</RequirePermission>;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="/account/password" element={<ChangePasswordPage />} />
        <Route path="/account/security" element={<AccountSecurityPage />} />
        <Route
          path="/patients"
          element={
            <Guarded nav="patients">
              <PatientsPage />
            </Guarded>
          }
        />
        <Route
          path="/patients/:id"
          element={
            <Guarded nav="patients">
              <PatientChart />
            </Guarded>
          }
        />
        <Route
          path="/queue"
          element={
            <Guarded nav="queue">
              <QueuePage />
            </Guarded>
          }
        />
        <Route
          path="/appointments"
          element={
            <Guarded nav="appointments">
              <AppointmentsPage />
            </Guarded>
          }
        />
        <Route
          path="/triage"
          element={
            <Guarded nav="triage">
              <TriagePage />
            </Guarded>
          }
        />
        <Route
          path="/consultations"
          element={
            <Guarded nav="consultations">
              <ConsultationsPage />
            </Guarded>
          }
        />
        <Route
          path="/consultations/:id"
          element={
            <RequirePermission anyOf={["clinical.view"]}>
              <ConsultationWorkspace />
            </RequirePermission>
          }
        />
        <Route
          path="/laboratory"
          element={
            <Guarded nav="laboratory">
              <LaboratoryPage />
            </Guarded>
          }
        />
        <Route
          path="/pharmacy"
          element={
            <Guarded nav="pharmacy">
              <PharmacyPage />
            </Guarded>
          }
        />
        <Route
          path="/inventory"
          element={
            <Guarded nav="inventory">
              <InventoryPage />
            </Guarded>
          }
        />
        <Route
          path="/billing"
          element={
            <Guarded nav="billing">
              <BillingPage />
            </Guarded>
          }
        />
        <Route
          path="/billing/invoices/:id"
          element={
            <Guarded nav="billing">
              <InvoicePage />
            </Guarded>
          }
        />
        <Route
          path="/approvals"
          element={
            <Guarded nav="approvals">
              <ApprovalsPage />
            </Guarded>
          }
        />
        <Route
          path="/reports"
          element={
            <Guarded nav="reports">
              <ReportsPage />
            </Guarded>
          }
        />
        <Route
          path="/calendar"
          element={
            <Guarded nav="calendar">
              <CalendarPage />
            </Guarded>
          }
        />
        <Route
          path="/catalogue"
          element={
            <Guarded nav="catalogue">
              <CataloguePage />
            </Guarded>
          }
        />
        <Route
          path="/admin/users"
          element={
            <Guarded nav="users">
              <UsersPage />
            </Guarded>
          }
        />
        <Route
          path="/admin/roles"
          element={
            <Guarded nav="roles">
              <RolesPage />
            </Guarded>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <Guarded nav="audit">
              <AuditPage />
            </Guarded>
          }
        />
        <Route
          path="/admin/clinic"
          element={
            <Guarded nav="clinic">
              <ClinicSettingsPage />
            </Guarded>
          }
        />
        <Route
          path="/admin/departments"
          element={
            <Guarded nav="departments">
              <DepartmentsPage />
            </Guarded>
          }
        />
        <Route
          path="/admin/system"
          element={
            <Guarded nav="system">
              <SystemPage />
            </Guarded>
          }
        />
        <Route
          path="/announcements"
          element={
            <Guarded nav="announcements">
              <AnnouncementsPage />
            </Guarded>
          }
        />
        <Route
          path="/admin/phones"
          element={
            <Guarded nav="phones">
              <PhonesPage />
            </Guarded>
          }
        />
        <Route
          path="/dental/encounters"
          element={
            <Guarded nav="dental_encounters">
              <DentalEncountersPage />
            </Guarded>
          }
        />
        <Route
          path="/dental/encounters/:id"
          element={
            <RequirePermission anyOf={["dental.view"]}>
              <DentalWorkspace />
            </RequirePermission>
          }
        />
        <Route
          path="/dental/patients/:id"
          element={
            <RequirePermission anyOf={["dental.view"]}>
              <DentalPatientPage />
            </RequirePermission>
          }
        />
        <Route
          path="/dental/recalls"
          element={
            <Guarded nav="recalls">
              <RecallsPage />
            </Guarded>
          }
        />
        <Route
          path="/dental/ortho"
          element={
            <Guarded nav="ortho">
              <OrthoCasesPage />
            </Guarded>
          }
        />
        <Route
          path="/dental/lab-cases"
          element={
            <Guarded nav="lab_cases">
              <LabCasesPage />
            </Guarded>
          }
        />
        <Route
          path="/dental/catalogue"
          element={
            <Guarded nav="dental_catalogue">
              <DentalCataloguePage />
            </Guarded>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

initTheme();
startTableLabels();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
