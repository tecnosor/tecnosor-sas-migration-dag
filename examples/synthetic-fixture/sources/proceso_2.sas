/***************************************************************************
 * SYNTHETIC FIXTURE - NOT A REAL SUBSIDIARY ESTATE                        *
 ***************************************************************************/

/* Process 2: monthly DQ reporting */

libname cust oracle path='DBPROD01' schema='CUST';

proc sql;
    create table work.dq_report as
    select region, count(*) as findings
    from cust.customer_dq
    where dq_score < 70
    group by region;
quit;
