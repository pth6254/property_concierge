export type ListingEntryContext = {
  name?: string;
  address?: string;
  propertyType?: string;
  caseId?: string;
  listingId?: string;
};

export function listingEntryHref(context: ListingEntryContext = {}): string {
  const params = new URLSearchParams();
  if (context.name) params.set("name", context.name);
  if (context.address) params.set("address", context.address);
  if (context.propertyType && context.propertyType !== "all") params.set("property_type", context.propertyType);
  if (context.caseId) params.set("case_id", context.caseId);
  if (context.listingId) params.set("listing_id", context.listingId);
  return `/listings${params.size ? `?${params}` : ""}${context.listingId ? "#saved-listings" : "#register-listing"}`;
}
