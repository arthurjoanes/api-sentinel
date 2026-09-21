// Expected values come from raw rows, never from an earlier HTTP 200.
export function correctResult(body, route, tenant, oracle) {
  const expected = oracle.tenants[tenant];
  if (!body || typeof body !== 'object') return false;

  if (route === 'stores') {
    return Array.isArray(body.items)
      && JSON.stringify(body.items.map(store => store.id)) === JSON.stringify(expected.stores);
  }
  if (route === 'erp') {
    return body.store_id === expected.store
      && body.sku === 'SKU-001'
      && body.available === expected.available;
  }
  if (body.dataset_version !== oracle.dataset_version || body.coverage?.complete !== true) {
    return false;
  }
  if (route === 'summary') {
    return body.store_id === expected.store
      && body.start === oracle.start
      && body.end === oracle.end
      && body.currency === 'BRL'
      && body.revenue_cents === expected.revenue_cents
      && body.order_count === expected.order_count
      && body.average_ticket_cents === expected.average_ticket_cents;
  }
  if (route === 'sales') {
    const fields = ['id', 'order_id', 'sku', 'quantity', 'unit_price_cents', 'line_total_cents'];
    return typeof body.next_cursor === 'string'
      && body.next_cursor.length > 0
      && Array.isArray(body.items)
      && body.items.length === expected.sales.length
      && body.items.every((item, index) => {
        const row = expected.sales[index];
        return fields.every(key => item[key] === row[key])
          && Date.parse(item.sold_at) === Date.parse(row.sold_at);
      });
  }
  return false;
}
