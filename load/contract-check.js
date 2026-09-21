import { correctResult } from './contracts.js';
export const options = {vus:1,iterations:1};
export default function () {
  const oracle = {start:'2026-01-01',end:'2026-01-01',dataset_version:'v1',tenants:{tenant_a:{store:1,stores:[1,2,3],revenue_cents:12500,order_count:2,average_ticket_cents:6250,available:21,sales:[{id:1,order_id:101,sku:'SKU-001',quantity:2,unit_price_cents:2500,line_total_cents:5000,sold_at:'2026-01-01T03:00:00Z'}]}}};
  const summary = {store_id:1,start:oracle.start,end:oracle.end,currency:'BRL',revenue_cents:12500,order_count:2,average_ticket_cents:6250,dataset_version:'v1',coverage:{complete:true}};
  if (!correctResult(summary,'summary','tenant_a',oracle)) throw new Error('Oráculo válido recusado');
  const changes = [{store_id:4},{revenue_cents:12501},{order_count:3},{average_ticket_cents:4167},{currency:'USD'},{end:'2026-01-02'},{dataset_version:'v2'},{coverage:{complete:false}}];
  for (const change of changes) if (correctResult({...summary,...change},'summary','tenant_a',oracle)) throw new Error('200 incorreto aceito: '+JSON.stringify(change));
  if (correctResult({items:[{id:4},{id:5},{id:6}]},'stores','tenant_a',oracle)) throw new Error('Tenant errado aceito');
  if (correctResult({store_id:4,sku:'SKU-001',available:21},'erp','tenant_a',oracle)) throw new Error('ERP de outra loja aceito');
  const sales = {dataset_version:'v1',coverage:{complete:true},next_cursor:'opaque',items:oracle.tenants.tenant_a.sales};
  if (!correctResult(sales,'sales','tenant_a',oracle)) throw new Error('Página válida recusada');
  if (correctResult({...sales,items:[{...sales.items[0],line_total_cents:1}]},'sales','tenant_a',oracle)) throw new Error('Item incorreto aceito');
  console.log('13 verificações de contrato: válidos aceitos e mutações rejeitadas. Sem HTTP.');
}
