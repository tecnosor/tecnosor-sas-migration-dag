/***************************************************************************
 * SYNTHETIC FIXTURE - NOT A REAL SUBSIDIARY ESTATE                        *
 * Purpose: validate the SASsessment foundation only.                      *
 ***************************************************************************/

/* Process 1: customer DQ revalidation batch job */

libname cust oracle path='DBPROD01' schema='CUST';

%include "shared_macros/fmt_check.sas";

proc sql;
    create table work.stg as
    select c.customer_id, c.country_code, a.postal_code
    from cust.customer_master c
    join cust.address_ext a
      on c.customer_id = a.customer_id;
quit;

data cust.customer_dq;
    set work.stg;
    format postal_code $fmt_checkRC.;
run;
